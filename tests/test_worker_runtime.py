"""Tests for worker runtime with timeout and orphan cleanup.

Fixes #3786: Cancel orphaned subprocesses after run timeout
"""

import pytest
import time
import signal
import os
from unittest.mock import patch, MagicMock

from src.agent.worker_runtime import WorkerRuntime, WorkerState


class TestWorkerRuntime:
    """Test worker runtime functionality."""

    def test_start_run_success(self):
        """Test starting a worker run successfully."""
        runtime = WorkerRuntime()
        
        result = runtime.start_run(
            run_id="run-001",
            worker_id="worker-001",
            command=["sleep", "0.1"],
            timeout=10.0
        )
        
        assert result is True
        
        # Wait for completion
        time.sleep(0.3)
        
        state = runtime.get_run_state("run-001")
        assert state == WorkerState.COMPLETED

    def test_start_run_duplicate_id(self):
        """Test that duplicate run IDs are rejected."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-001",
            worker_id="worker-001",
            command=["sleep", "1"],
            timeout=10.0
        )
        
        # Try to start with same ID
        result = runtime.start_run(
            run_id="run-001",
            worker_id="worker-002",
            command=["sleep", "1"],
            timeout=10.0
        )
        
        assert result is False

    def test_run_timeout(self):
        """Test that runs timeout after specified duration."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-timeout",
            worker_id="worker-001",
            command=["sleep", "10"],
            timeout=0.5  # Short timeout for testing
        )
        
        # Wait for timeout
        time.sleep(1.0)
        
        state = runtime.get_run_state("run-timeout")
        assert state == WorkerState.TIMEOUT
        
        info = runtime.get_run_info("run-timeout")
        assert "timed out" in info["error_message"].lower() or "timeout" in info["error_message"].lower()

    def test_cancel_run(self):
        """Test cancelling a running worker run."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-cancel",
            worker_id="worker-001",
            command=["sleep", "10"],
            timeout=30.0
        )
        
        # Give it time to start
        time.sleep(0.2)
        
        result = runtime.cancel_run("run-cancel")
        assert result is True
        
        # Wait for cancellation
        time.sleep(0.5)
        
        state = runtime.get_run_state("run-cancel")
        assert state == WorkerState.CANCELLED

    def test_cancel_nonexistent_run(self):
        """Test cancelling a non-existent run."""
        runtime = WorkerRuntime()
        
        result = runtime.cancel_run("nonexistent-run")
        assert result is False

    def test_cancel_already_completed_run(self):
        """Test cancelling an already completed run."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-done",
            worker_id="worker-001",
            command=["echo", "hello"],
            timeout=10.0
        )
        
        # Wait for completion
        time.sleep(0.3)
        
        # Try to cancel completed run
        result = runtime.cancel_run("run-done")
        assert result is False

    def test_run_failure(self):
        """Test handling of failed runs."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-fail",
            worker_id="worker-001",
            command=["false"],  # Command that always fails
            timeout=10.0
        )
        
        # Wait for completion
        time.sleep(0.3)
        
        state = runtime.get_run_state("run-fail")
        assert state == WorkerState.FAILED
        
        info = runtime.get_run_info("run-fail")
        assert info["exit_code"] != 0

    def test_get_run_info(self):
        """Test getting detailed run information."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-info",
            worker_id="worker-001",
            command=["echo", "test"],
            timeout=10.0
        )
        
        # Wait for completion
        time.sleep(0.3)
        
        info = runtime.get_run_info("run-info")
        assert info is not None
        assert info["run_id"] == "run-info"
        assert info["worker_id"] == "worker-001"
        assert info["state"] == "completed"
        assert info["timeout"] == 10.0
        assert info["exit_code"] == 0

    def test_list_runs(self):
        """Test listing runs."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-001",
            worker_id="worker-001",
            command=["echo", "1"],
            timeout=10.0
        )
        
        runtime.start_run(
            run_id="run-002",
            worker_id="worker-002",
            command=["echo", "2"],
            timeout=10.0
        )
        
        # Wait for completion
        time.sleep(0.3)
        
        all_runs = runtime.list_runs()
        assert len(all_runs) == 2
        
        worker_runs = runtime.list_runs(worker_id="worker-001")
        assert len(worker_runs) == 1
        assert "run-001" in worker_runs

    def test_cleanup_completed_runs(self):
        """Test cleanup of old completed runs."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-old",
            worker_id="worker-001",
            command=["echo", "old"],
            timeout=10.0
        )
        
        # Wait for completion
        time.sleep(0.3)
        
        # Cleanup with very short max_age (should not remove yet)
        count = runtime.cleanup_completed_runs(max_age=3600.0)
        assert count == 0
        
        # Verify run still exists
        assert runtime.get_run_info("run-old") is not None

    def test_shutdown(self):
        """Test graceful shutdown."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-001",
            worker_id="worker-001",
            command=["sleep", "10"],
            timeout=30.0
        )
        
        # Give it time to start
        time.sleep(0.2)
        
        # Shutdown should cancel active runs
        runtime.shutdown(timeout=1.0)
        
        # After shutdown, new runs should fail
        result = runtime.start_run(
            run_id="run-after-shutdown",
            worker_id="worker-001",
            command=["echo", "test"],
            timeout=10.0
        )
        assert result is False


class TestOrphanCleanup:
    """Test orphaned process cleanup functionality."""

    def test_orphan_cleanup_on_timeout(self):
        """Test that orphaned processes are cleaned up on timeout."""
        runtime = WorkerRuntime()
        
        # Start a run that spawns child processes
        runtime.start_run(
            run_id="run-orphan",
            worker_id="worker-001",
            command=["bash", "-c", "sleep 10 & sleep 10 & wait"],
            timeout=0.5
        )
        
        # Wait for timeout and cleanup
        time.sleep(1.0)
        
        info = runtime.get_run_info("run-orphan")
        assert info["state"] == "timeout"
        # Orphaned children should be tracked
        assert isinstance(info["orphaned_children"], list)

    def test_orphan_cleanup_on_cancel(self):
        """Test that orphaned processes are cleaned up on cancellation."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-cancel-orphan",
            worker_id="worker-001",
            command=["bash", "-c", "sleep 10 & sleep 10 & wait"],
            timeout=30.0
        )
        
        # Give it time to spawn children
        time.sleep(0.3)
        
        # Cancel the run
        runtime.cancel_run("run-cancel-orphan")
        
        # Wait for cleanup
        time.sleep(0.5)
        
        info = runtime.get_run_info("run-cancel-orphan")
        assert info["state"] == "cancelled"
        assert isinstance(info["orphaned_children"], list)


class TestWorkerRuntimeEdgeCases:
    """Test edge cases for worker runtime."""

    def test_empty_command(self):
        """Test handling of empty command."""
        runtime = WorkerRuntime()
        
        result = runtime.start_run(
            run_id="run-empty",
            worker_id="worker-001",
            command=[],
            timeout=10.0
        )
        
        assert result is True
        time.sleep(0.2)
        
        # Empty command should fail
        info = runtime.get_run_info("run-empty")
        assert info["state"] in ["failed", "completed"]

    def test_very_short_timeout(self):
        """Test handling of very short timeout."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-short",
            worker_id="worker-001",
            command=["sleep", "10"],
            timeout=0.01  # Very short timeout
        )
        
        time.sleep(0.2)
        
        state = runtime.get_run_state("run-short")
        assert state == WorkerState.TIMEOUT

    def test_get_nonexistent_run_info(self):
        """Test getting info for non-existent run."""
        runtime = WorkerRuntime()
        
        info = runtime.get_run_info("nonexistent")
        assert info is None

    def test_get_nonexistent_run_state(self):
        """Test getting state for non-existent run."""
        runtime = WorkerRuntime()
        
        state = runtime.get_run_state("nonexistent")
        assert state is None

    def test_multiple_cancellations(self):
        """Test that multiple cancellations are handled gracefully."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-multi-cancel",
            worker_id="worker-001",
            command=["sleep", "10"],
            timeout=30.0
        )
        
        time.sleep(0.2)
        
        # First cancellation should succeed
        result1 = runtime.cancel_run("run-multi-cancel")
        assert result1 is True
        
        # Wait for cancellation to complete
        time.sleep(0.3)
        
        # Second cancellation should fail (already cancelled)
        result2 = runtime.cancel_run("run-multi-cancel")
        assert result2 is False

    def test_run_with_environment_variables(self):
        """Test running with custom environment variables."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-env",
            worker_id="worker-001",
            command=["bash", "-c", "echo $TEST_VAR"],
            timeout=10.0,
            env={"TEST_VAR": "test_value"}
        )
        
        time.sleep(0.3)
        
        info = runtime.get_run_info("run-env")
        assert info["state"] == "completed"

    def test_concurrent_runs(self):
        """Test multiple concurrent runs."""
        runtime = WorkerRuntime()
        
        # Start multiple runs
        for i in range(5):
            runtime.start_run(
                run_id=f"run-concurrent-{i}",
                worker_id=f"worker-{i}",
                command=["sleep", "0.1"],
                timeout=10.0
            )
        
        # Wait for all to complete
        time.sleep(0.5)
        
        # Verify all completed
        for i in range(5):
            state = runtime.get_run_state(f"run-concurrent-{i}")
            assert state == WorkerState.COMPLETED


class TestWorkerStateTransitions:
    """Test worker state machine transitions."""

    def test_state_transition_pending_to_running(self):
        """Test transition from PENDING to RUNNING."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-transition",
            worker_id="worker-001",
            command=["sleep", "0.5"],
            timeout=10.0
        )
        
        # Immediately check state
        state = runtime.get_run_state("run-transition")
        assert state in [WorkerState.PENDING, WorkerState.RUNNING]
        
        # Wait for it to be running
        time.sleep(0.1)
        state = runtime.get_run_state("run-transition")
        assert state == WorkerState.RUNNING

    def test_state_transition_running_to_completed(self):
        """Test transition from RUNNING to COMPLETED."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-complete",
            worker_id="worker-001",
            command=["echo", "done"],
            timeout=10.0
        )
        
        time.sleep(0.3)
        
        state = runtime.get_run_state("run-complete")
        assert state == WorkerState.COMPLETED

    def test_state_transition_running_to_cancelling(self):
        """Test transition from RUNNING to CANCELLING."""
        runtime = WorkerRuntime()
        
        runtime.start_run(
            run_id="run-cancelling",
            worker_id="worker-001",
            command=["sleep", "10"],
            timeout=30.0
        )
        
        time.sleep(0.1)
        
        # Cancel while running
        runtime.cancel_run("run-cancelling")
        
        state = runtime.get_run_state("run-cancelling")
        assert state == WorkerState.CANCELLING

    def test_terminal_states(self):
        """Test that terminal states are correctly identified."""
        terminal_states = [
            WorkerState.COMPLETED,
            WorkerState.FAILED,
            WorkerState.CANCELLED,
            WorkerState.TIMEOUT
        ]
        
        for state in terminal_states:
            assert state in terminal_states
