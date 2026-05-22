"""Task Scheduler — Priority-based task queuing and dispatch with fairness budgets."""

import asyncio
import heapq
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

logger = logging.getLogger(__name__)


class PriorityClass(Enum):
    """Priority classes for workflow lanes."""
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class SchedulerError(Exception):
    """Base scheduler error."""
    pass


class FairnessBudgetExceeded(SchedulerError):
    """Raised when fairness budget for a priority class is exceeded."""
    pass


class InvalidStateTransition(SchedulerError):
    """Raised when an invalid state transition is attempted."""
    pass


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

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class FairnessBudget:
    """Manages fairness budget for a priority class."""
    
    def __init__(self, priority_class: PriorityClass, max_concurrent: int, max_queue_depth: int):
        self.priority_class = priority_class
        self.max_concurrent = max_concurrent
        self.max_queue_depth = max_queue_depth
        self._in_flight: Set[str] = set()
        self._queued: int = 0
        self._audit_log: List[Dict] = []
    
    def can_accept_task(self) -> bool:
        """Check if budget can accept another task."""
        return len(self._in_flight) < self.max_concurrent and self._queued < self.max_queue_depth
    
    def record_enqueue(self, task_id: str) -> None:
        """Record a task being queued."""
        self._queued += 1
        self._audit_log.append({
            "action": "enqueue",
            "task_id": task_id,
            "timestamp": time.time(),
            "priority_class": self.priority_class.value,
        })
    
    def record_dequeue(self, task_id: str) -> None:
        """Record a task being dequeued (moving from queued to in-flight)."""
        self._queued = max(0, self._queued - 1)
        self._in_flight.add(task_id)
        self._audit_log.append({
            "action": "dequeue",
            "task_id": task_id,
            "timestamp": time.time(),
            "priority_class": self.priority_class.value,
        })
    
    def record_complete(self, task_id: str) -> None:
        """Record a task completion."""
        self._in_flight.discard(task_id)
        self._audit_log.append({
            "action": "complete",
            "task_id": task_id,
            "timestamp": time.time(),
            "priority_class": self.priority_class.value,
        })
    
    def get_stats(self) -> Dict[str, Any]:
        """Get budget statistics (without exposing task details)."""
        return {
            "priority_class": self.priority_class.value,
            "in_flight_count": len(self._in_flight),
            "queued_count": self._queued,
            "utilization": len(self._in_flight) / self.max_concurrent if self.max_concurrent > 0 else 0,
        }


class TaskScheduler:
    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        
        # Fairness budgets by priority class
        self._fairness_budgets: Dict[PriorityClass, FairnessBudget] = {
            PriorityClass.URGENT: FairnessBudget(PriorityClass.URGENT, max_concurrent=10, max_queue_depth=100),
            PriorityClass.HIGH: FairnessBudget(PriorityClass.HIGH, max_concurrent=8, max_queue_depth=80),
            PriorityClass.NORMAL: FairnessBudget(PriorityClass.NORMAL, max_concurrent=5, max_queue_depth=50),
            PriorityClass.LOW: FairnessBudget(PriorityClass.LOW, max_concurrent=2, max_queue_depth=20),
        }
        
        # Task to priority class mapping
        self._task_priority_class: Dict[str, PriorityClass] = {}
    
    def _get_priority_class(self, priority: int) -> PriorityClass:
        """Map numeric priority to priority class."""
        if priority >= 100:
            return PriorityClass.URGENT
        elif priority >= 50:
            return PriorityClass.HIGH
        elif priority >= 10:
            return PriorityClass.NORMAL
        else:
            return PriorityClass.LOW
    
    def _check_atomic_precondition(self, priority_class: PriorityClass, task_id: str) -> bool:
        """Atomic state precondition check before committing scheduling decision."""
        budget = self._fairness_budgets[priority_class]
        
        # Check if budget can accept this task
        if not budget.can_accept_task():
            logger.warning(
                f"Fairness budget exceeded for {priority_class.value}: "
                f"in_flight={len(budget._in_flight)}, queued={budget._queued}"
            )
            return False
        
        # Check for duplicate task (stale/duplicate transition prevention)
        if task_id in self._in_flight:
            logger.warning(f"Task {task_id} already in flight - rejecting duplicate")
            return False
        
        return True

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        """Enqueue a task with fairness budget enforcement."""
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0
        
        # Determine priority class
        priority_class = self._get_priority_class(priority)
        task["priority_class"] = priority_class.value
        self._task_priority_class[task_id] = priority_class
        
        # Check fairness budget before accepting
        budget = self._fairness_budgets[priority_class]
        if not budget.can_accept_task():
            logger.error(
                f"FairnessBudgetExceeded: {priority_class.value} queue full "
                f"(max_depth={budget.max_queue_depth}, current={budget._queued})"
            )
            raise FairnessBudgetExceeded(
                f"Cannot enqueue task: {priority_class.value} budget exceeded"
            )
        
        # Record in budget
        budget.record_enqueue(task_id)
        
        # Add to queue
        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        
        logger.info(f"Task {task_id} enqueued with priority_class={priority_class.value}")
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        """Schedule a task for future execution."""
        task_id = str(uuid4())
        task["id"] = task_id
        task["scheduled_at"] = time.time()
        task["priority"] = priority
        
        # Determine priority class
        priority_class = self._get_priority_class(priority)
        task["priority_class"] = priority_class.value
        self._task_priority_class[task_id] = priority_class
        
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        """Dequeue a task with atomic precondition check."""
        now = time.time()
        
        # Process scheduled tasks
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid, None)
            if task:
                # Re-enqueue with same priority
                priority = task.get("priority", 0)
                self.enqueue(task, queue, priority)
        
        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                task_id = task["id"]
                priority_class = self._task_priority_class.get(task_id, PriorityClass.NORMAL)
                
                # Atomic state precondition check
                if not self._check_atomic_precondition(priority_class, task_id):
                    # Re-queue the task if precondition fails
                    logger.warning(f"Atomic precondition failed for task {task_id}, re-queueing")
                    self._queues[queue].push(task, task.get("priority", 0))
                    return None
                
                # Record in budget and mark as in-flight
                budget = self._fairness_budgets[priority_class]
                budget.record_dequeue(task_id)
                self._in_flight[task_id] = task
                
                logger.info(
                    f"Task {task_id} dequeued: priority_class={priority_class.value}, "
                    f"budget_stats={budget.get_stats()}"
                )
                return task
        return None

    def complete(self, task_id: str) -> bool:
        """Mark a task as complete."""
        task = self._in_flight.pop(task_id, None)
        if task:
            priority_class = self._task_priority_class.pop(task_id, PriorityClass.NORMAL)
            budget = self._fairness_budgets[priority_class]
            budget.record_complete(task_id)
            logger.info(f"Task {task_id} completed: priority_class={priority_class.value}")
            return True
        return False

    def fail(self, task_id: str, queue: str = "default") -> bool:
        """Mark a task as failed with retry logic."""
        task = self._in_flight.pop(task_id, None)
        if task:
            priority_class = self._task_priority_class.get(task_id, PriorityClass.NORMAL)
            budget = self._fairness_budgets[priority_class]
            budget.record_complete(task_id)  # Remove from in-flight
            
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                # Re-enqueue with same priority
                priority = task.get("priority", 0)
                try:
                    self.enqueue(task, queue, priority)
                    return True
                except FairnessBudgetExceeded:
                    logger.error(f"Cannot retry task {task_id}: budget exceeded")
                    return False
        return False
    
    def get_fairness_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get fairness budget statistics for all priority classes."""
        return {
            pc.value: budget.get_stats() for pc, budget in self._fairness_budgets.items()
        }


# 2019-04-25T08:37:12 update

# 2019-06-04T16:40:00 update

# 2019-07-11T12:01:28 update

# 2019-08-02T12:20:21 update

# 2019-08-23T10:38:50 update

# 2019-10-31T13:55:52 update

# 2019-11-04T20:12:32 update

# 2019-12-13T12:22:36 update

# 2020-02-01T10:32:37 update

# 2020-02-26T09:44:38 update

# 2020-03-09T19:00:55 update

# 2020-05-01T18:40:34 update

# 2020-05-12T15:10:31 update

# 2020-06-30T13:24:19 update

# 2020-09-22T16:00:45 update

# 2020-10-20T10:52:48 update

# 2020-10-21T12:18:08 update

# 2020-11-06T12:35:01 update

# 2020-12-09T08:09:33 update

# 2021-01-07T08:20:36 update

# 2021-10-02T15:23:16 update

# 2021-10-06T16:14:57 update

# 2021-10-06T09:27:41 update

# 2021-11-19T08:37:40 update

# 2022-03-01T16:39:54 update

# 2022-05-26T13:43:07 update

# 2022-06-02T10:50:58 update

# 2022-06-14T10:46:48 update

# 2022-07-31T16:44:34 update

# 2022-08-30T18:20:12 update

# 2022-11-04T14:47:03 update

# 2022-12-06T10:36:49 update

# 2022-12-22T13:21:12 update

# 2022-12-26T12:24:50 update

# 2023-03-09T08:09:55 update

# 2023-05-01T10:07:37 update

# 2023-06-08T14:32:15 update

# 2023-07-14T17:24:18 update

# 2023-12-14T08:38:31 update

# 2024-02-20T13:43:58 update

# 2024-03-24T08:52:42 update

# 2024-03-28T15:27:17 update

# 2024-03-29T18:10:33 update

# 2024-04-15T20:18:31 update

# 2024-05-27T13:11:52 update

# 2024-05-27T16:42:56 update

# 2024-06-20T13:03:45 update

# 2024-06-28T12:32:58 update

# 2024-07-10T14:10:16 update

# 2024-07-26T14:18:59 update

# 2024-08-12T08:21:05 update

# 2024-08-21T16:58:40 update

# 2024-09-27T19:54:30 update

# 2024-10-21T13:47:42 update

# 2024-11-11T09:19:27 update

# 2024-12-24T08:23:41 update

# 2025-02-14T10:35:15 update

# 2025-03-31T18:09:40 update

# 2025-06-21T17:32:49 update

# 2025-07-21T16:52:28 update

# 2025-08-20T19:45:16 update

# 2025-11-04T18:54:24 update

# 2025-12-09T20:17:36 update

# 2026-01-12T15:42:32 update

# 2026-01-23T14:41:20 update

# 2026-03-18T14:43:07 update

# 2026-04-13T11:43:19 update
