"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import logging
import time
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from src.common.metrics import metrics

logger = logging.getLogger(__name__)

# Lifecycle states that indicate cancellation
CANCELLED_LIFECYCLES: Set[str] = {"cancelled", "canceled", "cancelling", "canceling"}


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    """Priority-based task scheduler with cancellation propagation."""
    
    def __init__(self, max_retries: int = 3, max_audit_log: int = 1000):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, Dict[str, Any]] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = max_retries
        self._cancelled_parents: Set[str] = set()
        self._task_state: Dict[str, Dict[str, Any]] = {}
        self.retry_audit_log: List[Dict[str, Any]] = []
        self._max_audit_log = max_audit_log

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0, parent_id: Optional[str] = None) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task.setdefault("retries", 0)
        task.setdefault("attempt", 0)
        task.setdefault("revision", 0)
        
        if parent_id:
            task["parent_id"] = parent_id
            self._task_state[task_id] = {"parent_id": parent_id, "lifecycle": "queued"}
        
        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, s in self._scheduled.items() if s.get("run_at", 0) <= now]
        for tid in expired:
            scheduled = self._scheduled.pop(tid)
            task = scheduled.get("task")
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                task["lifecycle"] = "running"
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["lifecycle"] = "completed"
            return True
        return False

    def cancel_parent(self, parent_id: str) -> None:
        """Mark parent as cancelled to prevent child retries."""
        self._cancelled_parents.add(parent_id)
        metrics.increment("scheduler.parent_cancelled")
        logger.info(f"Parent {parent_id} cancelled", extra={"parent_id": parent_id})

    def cancel(self, task_id: str, reason: str = "unknown") -> bool:
        """Cancel a task and track it."""
        task = self._in_flight.pop(task_id, None)
        if task:
            task["lifecycle"] = "cancelled"
            metrics.increment("scheduler.task_cancelled")
            logger.info(f"Task {task_id} cancelled", extra={"task_id": task_id, "reason": reason})
            return True
        return False

    def is_cancelled(self, task_id: str) -> bool:
        return task_id in self._cancelled_parents

    def is_lifecycle_cancelled(self, lifecycle: Optional[str]) -> bool:
        return lifecycle is not None and lifecycle.lower() in CANCELLED_LIFECYCLES

    def get_task_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get the current state of a task."""
        return self._task_state.get(task_id)

    def _cleanup_old_cancellations(self) -> None:
        """Placeholder for TTL cleanup."""
        pass

    def _audit_retry(self, task: Dict, decision: str, reason: str) -> None:
        """Record retry decision to bounded audit log."""
        audit = {
            "timestamp": time.time(),
            "task_id": task.get("id"),
            "parent_id": task.get("parent_id"),
            "decision": decision,
            "reason": reason,
            "attempt": task.get("attempt", 0),
            "revision": task.get("revision", 0),
        }
        self.retry_audit_log.append(audit)
        if len(self.retry_audit_log) > self._max_audit_log:
            self.retry_audit_log = self.retry_audit_log[-self._max_audit_log:]

    def fail(self, task_id: str, queue: str = "default", 
             expected_attempt: Optional[int] = None, 
             expected_revision: Optional[int] = None,
             parent_lifecycle: Optional[str] = None) -> bool:
        """Handle task failure with cancellation and stale retry checks."""
        task = self._in_flight.get(task_id)
        if not task:
            return False
        
        # Check for stale retry signals
        if expected_attempt is not None and task.get("attempt", 0) != expected_attempt:
            task["retry_rejected_reason"] = "stale_attempt"
            self._audit_retry(task, "rejected", "stale_attempt")
            metrics.increment("scheduler.retry_suppressed.stale_attempt")
            return False
        
        if expected_revision is not None and task.get("revision", 0) != expected_revision:
            task["retry_rejected_reason"] = "stale_revision"
            self._audit_retry(task, "rejected", "stale_revision")
            metrics.increment("scheduler.retry_suppressed.stale_revision")
            return False
        
        parent_id = task.get("parent_id")
        
        # Check parent cancellation via lifecycle or registry
        if parent_lifecycle and self.is_lifecycle_cancelled(parent_lifecycle):
            task["retry_rejected_reason"] = "parent_cancelled"
            task["lifecycle"] = "cancelled"
            self._audit_retry(task, "rejected", "parent_cancelled")
            logger.info(f"Task {task_id} not retried: parent lifecycle cancelled", 
                       extra={"task_id": task_id, "parent_id": parent_id})
            metrics.increment("scheduler.retry_suppressed.parent_cancelled")
            return False
        
        if parent_id and self.is_cancelled(parent_id):
            task["retry_rejected_reason"] = "parent_cancelled"
            task["lifecycle"] = "cancelled"
            self._audit_retry(task, "rejected", "parent_cancelled")
            logger.info(f"Task {task_id} not retried: parent {parent_id} cancelled",
                       extra={"task_id": task_id, "parent_id": parent_id})
            metrics.increment("scheduler.retry_suppressed.parent_cancelled")
            return False
        
        # Attempt retry
        task["retries"] += 1
        task["attempt"] = task.get("attempt", 0) + 1
        task["revision"] = task.get("revision", 0) + 1
        
        if task["retries"] < self._max_retries:
            task["lifecycle"] = "queued"
            self._audit_retry(task, "accepted", "retry_enqueued")
            logger.info(f"Task {task_id} retrying (attempt {task['attempt']})",
                       extra={"task_id": task_id, "attempt": task["attempt"]})
            metrics.increment("scheduler.task_retried")
            self._in_flight.pop(task_id, None)
            self.enqueue(task, queue, priority=task.get("priority", 0), parent_id=parent_id)
            return True
        else:
            task["lifecycle"] = "failed"
            self._audit_retry(task, "rejected", "max_retries_exceeded")
            logger.warning(f"Task {task_id} max retries exceeded",
                          extra={"task_id": task_id, "retries": task["retries"]})
            metrics.increment("scheduler.retry_exhausted")
            self._in_flight.pop(task_id, None)
            return False

# 2019-04-25T08:37:12 update
