"""Worker Runtime — Manages worker processes with timeout and cancellation.

Fixes #3786: Cancel orphaned subprocesses after run timeout
"""

import os
import signal
import subprocess
import logging
import time
import threading
from enum import Enum, auto
from typing import Dict, Optional, List, Set
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

logger = logging.getLogger(__name__)


class WorkerState(Enum):
    """Worker execution states."""
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class WorkerRun:
    """Represents a worker run with its state and metadata."""
    run_id: str
    worker_id: str
    command: List[str]
    timeout: float
    state: WorkerState = WorkerState.PENDING
    process: Optional[subprocess.Popen] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    exit_code: Optional[int] = None
    error_message: Optional[str] = None
    orphaned_children: List[int] = field(default_factory=list)


class WorkerRuntime:
    """Manages worker processes with timeout and orphan cleanup.
    
    Ensures that:
    1. Worker runs have a bounded execution time (timeout)
    2. Cancellation propagates to all child processes
    3. No orphaned processes remain after timeout or cancellation
    4. Each run has one durable terminal state
    """
    
    def __init__(self, default_timeout: float = 300.0):
        self._default_timeout = default_timeout
        self._runs: Dict[str, WorkerRun] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=10)
        self._shutdown = False
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals by cancelling all runs."""
        logger.info(f"Received signal {signum}, shutting down worker runtime...")
        self.shutdown()
    
    def start_run(self, run_id: str, worker_id: str, command: List[str],
                  timeout: Optional[float] = None, env: Optional[Dict] = None) -> bool:
        """Start a new worker run with timeout protection.
        
        Args:
            run_id: Unique identifier for this run
            worker_id: Worker identifier
            command: Command to execute
            timeout: Maximum execution time in seconds
            env: Environment variables
            
        Returns:
            True if run started successfully, False otherwise
        """
        with self._lock:
            if run_id in self._runs:
                logger.warning(f"Run {run_id} already exists")
                return False
            
            if self._shutdown:
                logger.error("Worker runtime is shutting down")
                return False
            
            run = WorkerRun(
                run_id=run_id,
                worker_id=worker_id,
                command=command,
                timeout=timeout or self._default_timeout
            )
            self._runs[run_id] = run
        
        # Start the run in a separate thread
        future = self._executor.submit(self._execute_run, run, env)
        
        # Setup timeout watcher
        self._executor.submit(self._timeout_watcher, run_id, run.timeout)
        
        logger.info(f"Started run {run_id} for worker {worker_id} (timeout: {run.timeout}s)")
        return True
    
    def _execute_run(self, run: WorkerRun, env: Optional[Dict]) -> None:
        """Execute a worker run and manage its lifecycle."""
        run.start_time = time.time()
        run.state = WorkerState.RUNNING
        
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        process_env["AO_RUN_ID"] = run.run_id
        process_env["AO_WORKER_ID"] = run.worker_id
        
        cancelled_during_execution = False
        
        try:
            # Start the process
            run.process = subprocess.Popen(
                run.command,
                env=process_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True  # Create new process group for cleanup
            )
            
            logger.info(f"Run {run.run_id} started (PID: {run.process.pid})")
            
            # Wait for completion with periodic checks
            while run.process.poll() is None:
                # Check if cancellation was requested
                with self._lock:
                    if run.state == WorkerState.CANCELLING:
                        cancelled_during_execution = True
                        self._cancel_run_internal(run)
                        return
                
                time.sleep(0.1)
            
            # Process completed
            run.exit_code = run.process.returncode
            run.end_time = time.time()
            
            # Check if this was a timeout (process was killed)
            if run.exit_code == -15 or run.exit_code == -9:  # SIGTERM or SIGKILL
                with self._lock:
                    # If state was already set to TIMEOUT or CANCELLED, keep it
                    if run.state not in (WorkerState.TIMEOUT, WorkerState.CANCELLED):
                        run.state = WorkerState.FAILED
                        run.error_message = f"Process terminated with code {run.exit_code}"
                        logger.warning(f"Run {run.run_id} terminated with exit code {run.exit_code}")
            elif run.exit_code == 0:
                run.state = WorkerState.COMPLETED
                logger.info(f"Run {run.run_id} completed successfully")
            else:
                run.state = WorkerState.FAILED
                run.error_message = f"Process exited with code {run.exit_code}"
                logger.warning(f"Run {run.run_id} failed with exit code {run.exit_code}")
                
        except Exception as e:
            if not cancelled_during_execution:
                run.state = WorkerState.FAILED
                run.error_message = str(e)
                run.end_time = time.time()
                logger.error(f"Run {run.run_id} failed: {e}")
    
    def _timeout_watcher(self, run_id: str, timeout: float) -> None:
        """Watch for timeout and cancel run if exceeded."""
        time.sleep(timeout)
        
        with self._lock:
            run = self._runs.get(run_id)
            if not run or run.state in (WorkerState.COMPLETED, WorkerState.FAILED, 
                                        WorkerState.CANCELLED, WorkerState.TIMEOUT):
                return
        
        logger.warning(f"Run {run_id} timed out after {timeout}s")
        self.cancel_run(run_id, reason="timeout")
    
    def cancel_run(self, run_id: str, reason: str = "user_request") -> bool:
        """Cancel a running worker run and cleanup orphaned processes.
        
        Args:
            run_id: Run identifier
            reason: Reason for cancellation
            
        Returns:
            True if cancellation was initiated, False if run not found
        """
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                logger.warning(f"Run {run_id} not found for cancellation")
                return False
            
            if run.state in (WorkerState.COMPLETED, WorkerState.FAILED, 
                            WorkerState.CANCELLED, WorkerState.TIMEOUT):
                logger.info(f"Run {run_id} already in terminal state: {run.state}")
                return False
            
            run.state = WorkerState.CANCELLING
        
        logger.info(f"Cancelling run {run_id} (reason: {reason})")
        self._cancel_run_internal(run, reason)
        return True
    
    def _cancel_run_internal(self, run: WorkerRun, reason: str = "user_request") -> None:
        """Internal cancellation logic with orphan cleanup."""
        if not run.process:
            run.end_time = time.time()
            if reason == "timeout":
                run.state = WorkerState.TIMEOUT
                run.error_message = f"Run timed out after {run.timeout}s"
            else:
                run.state = WorkerState.CANCELLED
                run.error_message = f"Run cancelled (reason: {reason})"
            return
        
        pid = run.process.pid
        
        try:
            # Set state immediately so _execute_run knows this was a cancellation
            run.end_time = time.time()
            if reason == "timeout":
                run.state = WorkerState.TIMEOUT
                run.error_message = f"Run timed out after {run.timeout}s"
            else:
                run.state = WorkerState.CANCELLED
                run.error_message = f"Run cancelled (reason: {reason})"
            
            # Try graceful termination first
            try:
                run.process.send_signal(signal.SIGTERM)
                # Wait for graceful shutdown
                run.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # Force kill if graceful shutdown fails
                logger.warning(f"Force killing run {run.run_id} (PID: {pid})")
                run.process.kill()
                run.process.wait()
            
            # Cleanup orphaned child processes
            self._cleanup_orphaned_processes(run, pid)
            
            logger.info(f"Run {run.run_id} cancelled and cleaned up")
            
        except Exception as e:
            logger.error(f"Error cancelling run {run.run_id}: {e}")
            if run.state not in (WorkerState.TIMEOUT, WorkerState.CANCELLED):
                run.state = WorkerState.FAILED
                run.error_message = f"Cancellation failed: {e}"
                run.end_time = time.time()
    
    def _cleanup_orphaned_processes(self, run: WorkerRun, parent_pid: int) -> None:
        """Find and terminate orphaned child processes.
        
        This is the key fix for #3786 - ensures no orphaned subprocesses remain.
        """
        orphaned_pids = self._find_child_processes(parent_pid)
        
        for child_pid in orphaned_pids:
            try:
                os.kill(child_pid, signal.SIGTERM)
                logger.info(f"Terminated orphaned process {child_pid} for run {run.run_id}")
                run.orphaned_children.append(child_pid)
            except ProcessLookupError:
                # Process already terminated
                pass
            except Exception as e:
                logger.warning(f"Failed to terminate orphaned process {child_pid}: {e}")
        
        # Give processes time to terminate gracefully
        time.sleep(0.5)
        
        # Force kill any remaining orphans
        for child_pid in orphaned_pids:
            try:
                os.kill(child_pid, signal.SIGKILL)
                logger.info(f"Force killed orphaned process {child_pid}")
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.warning(f"Failed to force kill orphaned process {child_pid}: {e}")
    
    def _find_child_processes(self, parent_pid: int) -> List[int]:
        """Find all child processes of a given parent PID."""
        children = []
        try:
            # Read process information from /proc
            for pid_str in os.listdir('/proc'):
                if not pid_str.isdigit():
                    continue
                
                try:
                    with open(f'/proc/{pid_str}/stat', 'r') as f:
                        stat = f.read()
                        # Extract parent PID from stat (field 4)
                        parts = stat.split()
                        if len(parts) >= 4:
                            ppid = int(parts[3])
                            if ppid == parent_pid:
                                children.append(int(pid_str))
                except (IOError, OSError):
                    continue
        except Exception as e:
            logger.warning(f"Error finding child processes: {e}")
        
        return children
    
    def get_run_state(self, run_id: str) -> Optional[WorkerState]:
        """Get the current state of a run."""
        with self._lock:
            run = self._runs.get(run_id)
            return run.state if run else None
    
    def get_run_info(self, run_id: str) -> Optional[Dict]:
        """Get detailed information about a run."""
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return None
            
            return {
                "run_id": run.run_id,
                "worker_id": run.worker_id,
                "state": run.state.value,
                "timeout": run.timeout,
                "start_time": run.start_time,
                "end_time": run.end_time,
                "exit_code": run.exit_code,
                "error_message": run.error_message,
                "orphaned_children": run.orphaned_children,
                "duration": run.end_time - run.start_time if run.end_time and run.start_time else None
            }
    
    def list_runs(self, worker_id: Optional[str] = None) -> List[str]:
        """List all run IDs, optionally filtered by worker."""
        with self._lock:
            if worker_id:
                return [r.run_id for r in self._runs.values() if r.worker_id == worker_id]
            return list(self._runs.keys())
    
    def cleanup_completed_runs(self, max_age: float = 3600.0) -> int:
        """Clean up completed runs older than max_age seconds.
        
        Returns:
            Number of runs cleaned up
        """
        current_time = time.time()
        to_remove = []
        
        with self._lock:
            for run_id, run in self._runs.items():
                if run.state in (WorkerState.COMPLETED, WorkerState.FAILED, 
                                WorkerState.CANCELLED, WorkerState.TIMEOUT):
                    if run.end_time and (current_time - run.end_time) > max_age:
                        to_remove.append(run_id)
            
            for run_id in to_remove:
                del self._runs[run_id]
        
        logger.info(f"Cleaned up {len(to_remove)} completed runs")
        return len(to_remove)
    
    def shutdown(self, timeout: float = 30.0) -> None:
        """Gracefully shutdown the worker runtime.
        
        Cancels all running runs and waits for cleanup.
        """
        logger.info("Shutting down worker runtime...")
        self._shutdown = True
        
        # Cancel all active runs
        with self._lock:
            active_runs = [
                run_id for run_id, run in self._runs.items()
                if run.state in (WorkerState.PENDING, WorkerState.RUNNING, WorkerState.CANCELLING)
            ]
        
        for run_id in active_runs:
            self.cancel_run(run_id, reason="runtime_shutdown")
        
        # Wait for cleanup
        time.sleep(min(timeout, 5.0))
        
        # Shutdown executor
        self._executor.shutdown(wait=True)
        logger.info("Worker runtime shutdown complete")
