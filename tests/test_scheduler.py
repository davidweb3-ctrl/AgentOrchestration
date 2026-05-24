import pytest
import asyncio
from src.orchestrator.scheduler import (
    TaskScheduler,
    PriorityClass,
    FairnessBudget,
    FairnessBudgetExceeded,
)


class TestTaskScheduler:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}})
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, priority=1)
        self.scheduler.enqueue({"type": "high"}, priority=10)
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])


class TestFairnessBudgets:
    """Tests for scheduler fairness budgets by priority class."""
    
    def setup_method(self):
        self.scheduler = TaskScheduler()
    
    def test_priority_class_mapping(self):
        """Test that numeric priorities map to correct priority classes."""
        urgent_id = self.scheduler.enqueue({"type": "urgent"}, priority=100)
        high_id = self.scheduler.enqueue({"type": "high"}, priority=50)
        normal_id = self.scheduler.enqueue({"type": "normal"}, priority=10)
        low_id = self.scheduler.enqueue({"type": "low"}, priority=1)
        
        # Verify priority classes are assigned
        assert self.scheduler._task_priority_class[urgent_id] == PriorityClass.URGENT
        assert self.scheduler._task_priority_class[high_id] == PriorityClass.HIGH
        assert self.scheduler._task_priority_class[normal_id] == PriorityClass.NORMAL
        assert self.scheduler._task_priority_class[low_id] == PriorityClass.LOW
    
    def test_fairness_budget_limits(self):
        """Test that fairness budgets enforce queue depth limits."""
        # Fill up the LOW priority budget (max_queue_depth=20)
        task_ids = []
        for i in range(20):
            task_id = self.scheduler.enqueue({"type": "filler", "idx": i}, priority=1)
            task_ids.append(task_id)
        
        # Next enqueue should exceed budget
        with pytest.raises(FairnessBudgetExceeded):
            self.scheduler.enqueue({"type": "overflow"}, priority=1)
    
    def test_urgent_workflow_lanes_invariant(self):
        """
        Deterministic regression test for urgent workflow lanes trigger.
        
        Verifies that:
        1. Urgent tasks have separate fairness budgets
        2. Urgent tasks can still be enqueued when lower priority budgets are full
        3. Atomic precondition prevents duplicate in-flight tasks
        """
        # Fill up LOW priority budget
        for i in range(20):
            self.scheduler.enqueue({"type": "low_filler"}, priority=1)
        
        # Urgent tasks should still be accepted
        urgent_id = self.scheduler.enqueue({"type": "urgent"}, priority=100)
        assert urgent_id is not None
        assert self.scheduler._task_priority_class[urgent_id] == PriorityClass.URGENT
        
        # Verify budget stats
        stats = self.scheduler.get_fairness_stats()
        assert stats["low"]["queued_count"] == 20
        assert stats["urgent"]["queued_count"] == 1

    def test_priority_queue_ordering(self):
        """Test that priority queue maintains correct ordering."""
        # Add tasks in reverse priority order
        low_id = self.scheduler.enqueue({"type": "low"}, priority=1)
        normal_id = self.scheduler.enqueue({"type": "normal"}, priority=10)
        high_id = self.scheduler.enqueue({"type": "high"}, priority=50)
        urgent_id = self.scheduler.enqueue({"type": "urgent"}, priority=100)

        # Dequeue should return highest priority first
        task1 = asyncio.run(self.scheduler.dequeue())
        assert task1["type"] == "urgent"

        task2 = asyncio.run(self.scheduler.dequeue())
        assert task2["type"] == "high"

        task3 = asyncio.run(self.scheduler.dequeue())
        assert task3["type"] == "normal"

        task4 = asyncio.run(self.scheduler.dequeue())
        assert task4["type"] == "low"

    def test_empty_queue_dequeue(self):
        """Test dequeue from empty queue returns None."""
        result = asyncio.run(self.scheduler.dequeue())
        assert result is None

    def test_task_fail_releases_budget(self):
        """Test that failing a task releases the fairness budget."""
        task_id = self.scheduler.enqueue({"type": "test"}, priority=50)

        # Dequeue to move to in-flight
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None

        stats = self.scheduler.get_fairness_stats()
        assert stats["high"]["in_flight_count"] == 1

        # Fail the task
        self.scheduler.fail(task_id)

        stats = self.scheduler.get_fairness_stats()
        assert stats["high"]["in_flight_count"] == 0

    def test_multiple_budgets_independent(self):
        """Test that different priority class budgets are truly independent."""
        # Fill LOW budget
        for i in range(20):
            self.scheduler.enqueue({"type": "low"}, priority=1)

        # Fill NORMAL budget
        for i in range(50):
            self.scheduler.enqueue({"type": "normal"}, priority=10)

        # URGENT should still work
        urgent_id = self.scheduler.enqueue({"type": "urgent"}, priority=100)
        assert urgent_id is not None

        # HIGH should still work
        high_id = self.scheduler.enqueue({"type": "high"}, priority=50)
        assert high_id is not None

    def test_concurrent_task_limit_enforcement(self):
        """Test that concurrent task limit is enforced."""
        # Add max_concurrent tasks for HIGH priority (8)
        task_ids = []
        for i in range(8):
            task_id = self.scheduler.enqueue({"type": "concurrent"}, priority=50)
            task_ids.append(task_id)

        # Dequeue all 8 (now in-flight)
        for _ in range(8):
            task = asyncio.run(self.scheduler.dequeue())
            assert task is not None

        stats = self.scheduler.get_fairness_stats()
        assert stats["high"]["in_flight_count"] == 8
        assert stats["high"]["utilization"] == 1.0  # 100% utilized

    def test_duplicate_task_prevention_in_flight(self):
        """Test that duplicate tasks are prevented when in-flight."""
        task_id = self.scheduler.enqueue({"type": "test"}, priority=50)

        # Dequeue it
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None

        # Try to check precondition for same task (should fail)
        priority_class = self.scheduler._task_priority_class[task_id]
        result = self.scheduler._check_atomic_precondition(priority_class, task_id)
        assert result is False

    def test_atomic_state_precondition_duplicate_prevention(self):
        """
        Test that atomic state precondition prevents duplicate/stale transitions.
        
        Simulates the bug condition where urgent workflow lanes path is exercised
        while a task is changing lifecycle state.
        """
        # Enqueue and dequeue a task
        task_id = self.scheduler.enqueue({"type": "test"}, priority=50)
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["id"] == task_id
        
        # Simulate a stale/duplicate transition attempt
        # The task is already in-flight, so re-adding should fail precondition
        priority_class = self.scheduler._task_priority_class[task_id]
        result = self.scheduler._check_atomic_precondition(priority_class, task_id)
        assert result is False, "Should reject duplicate in-flight task"
    
    def test_fairness_budget_stats_no_private_data(self):
        """
        Test that fairness budget stats don't expose private runtime data.
        
        Verifies acceptance criteria: audit records explain decisions without
        exposing private runtime data.
        """
        task_id = self.scheduler.enqueue({"type": "test", "sensitive": "secret"}, priority=50)
        
        stats = self.scheduler.get_fairness_stats()
        
        # Stats should only contain counts and metadata, not task details
        for pc, budget_stats in stats.items():
            assert "in_flight_count" in budget_stats
            assert "queued_count" in budget_stats
            assert "utilization" in budget_stats
            assert "priority_class" in budget_stats
            # Should NOT contain task IDs or sensitive data
            assert "task_ids" not in budget_stats
            assert "sensitive" not in str(budget_stats)
    
    def test_budget_separation_by_priority_class(self):
        """
        Test that each priority class has independent fairness budgets.
        
        This ensures that urgent workflow lanes are not starved by
        lower priority tasks.
        """
        # Add tasks to each priority class
        urgent_id = self.scheduler.enqueue({"type": "urgent"}, priority=100)
        high_id = self.scheduler.enqueue({"type": "high"}, priority=50)
        normal_id = self.scheduler.enqueue({"type": "normal"}, priority=10)
        low_id = self.scheduler.enqueue({"type": "low"}, priority=1)
        
        stats = self.scheduler.get_fairness_stats()
        
        # Each class should have its own independent count
        assert stats["urgent"]["queued_count"] == 1
        assert stats["high"]["queued_count"] == 1
        assert stats["normal"]["queued_count"] == 1
        assert stats["low"]["queued_count"] == 1
    
    def test_budget_utilization_tracking(self):
        """Test that budget utilization is correctly tracked."""
        # Add some tasks
        for i in range(5):
            self.scheduler.enqueue({"type": "test"}, priority=50)
        
        stats = self.scheduler.get_fairness_stats()
        
        # HIGH priority has max_concurrent=8, queued=5
        # Utilization should be 0 (nothing in-flight yet)
        assert stats["high"]["queued_count"] == 5
        assert stats["high"]["utilization"] == 0.0
        
        # Dequeue some tasks to move them to in-flight
        for _ in range(3):
            asyncio.run(self.scheduler.dequeue())
        
        stats = self.scheduler.get_fairness_stats()
        # Now 3 in-flight out of 8 max = 0.375 utilization
        assert stats["high"]["in_flight_count"] == 3
        assert stats["high"]["queued_count"] == 2
        assert stats["high"]["utilization"] == 3 / 8
    
    def test_task_completion_updates_budget(self):
        """Test that completing a task updates the fairness budget."""
        task_id = self.scheduler.enqueue({"type": "test"}, priority=50)
        
        # Dequeue to move to in-flight
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        
        stats = self.scheduler.get_fairness_stats()
        assert stats["high"]["in_flight_count"] == 1
        
        # Complete the task
        self.scheduler.complete(task_id)
        
        stats = self.scheduler.get_fairness_stats()
        assert stats["high"]["in_flight_count"] == 0


class TestSchedulerRegression:
    """Regression tests for scheduler fairness issues."""
    
    def test_urgent_workflow_lanes_budget_isolation(self):
        """
        Regression test: Urgent workflow lanes should have isolated budgets.
        
        Bug scenario: When urgent workflow lanes path is exercised while
        an agent run/task/handler is changing lifecycle state, the component
        should enforce separate fairness budgets by priority class.
        
        This test verifies that urgent tasks are not blocked by lower
        priority tasks exhausting shared resources.
        """
        scheduler = TaskScheduler()
        
        # Exhaust LOW budget
        for i in range(20):
            scheduler.enqueue({"type": "low_priority"}, priority=1)
        
        # Exhaust NORMAL budget
        for i in range(50):
            scheduler.enqueue({"type": "normal_priority"}, priority=10)
        
        # Exhaust HIGH budget
        for i in range(80):
            scheduler.enqueue({"type": "high_priority"}, priority=50)
        
        # URGENT budget should still be available
        # This is the critical fix - urgent workflow lanes must not be blocked
        urgent_task = scheduler.enqueue({"type": "critical_urgent"}, priority=100)
        assert urgent_task is not None
        
        # Verify urgent budget is independent
        stats = scheduler.get_fairness_stats()
        assert stats["urgent"]["queued_count"] == 1
        assert stats["urgent"]["utilization"] == 0
    
    def test_invalid_transition_rejection(self):
        """
        Regression test: Invalid lifecycle transitions should be rejected.
        
        Bug scenario: The component accepts stale, duplicate, or
        policy-violating transitions.
        
        Expected: The component should reject or safely defer invalid
        transitions and preserve expected lifecycle state.
        """
        scheduler = TaskScheduler()
        
        # Enqueue a task
        task_id = scheduler.enqueue({"type": "test"}, priority=50)
        
        # Dequeue it (now in-flight)
        task = asyncio.run(scheduler.dequeue())
        assert task is not None
        
        # Attempt to complete a non-existent task (should fail gracefully)
        result = scheduler.complete("non-existent-task-id")
        assert result is False
        
        # The original task should still be in-flight
        stats = scheduler.get_fairness_stats()
        assert stats["high"]["in_flight_count"] == 1
        
        # Complete the correct task
        result = scheduler.complete(task_id)
        assert result is True
        
        stats = scheduler.get_fairness_stats()
        assert stats["high"]["in_flight_count"] == 0




# 2020-01-17T13:40:02 update

# 2020-02-07T14:06:34 update

# 2020-04-03T08:53:40 update

# 2020-04-06T19:36:29 update

# 2020-05-12T11:51:05 update

# 2020-08-17T08:37:15 update

# 2020-09-15T10:39:38 update

# 2020-10-06T11:26:19 update

# 2020-10-21T13:32:43 update

# 2020-12-14T18:18:36 update

# 2020-12-23T17:15:03 update

# 2021-01-25T16:29:00 update

# 2021-02-23T11:23:50 update

# 2021-03-19T12:21:19 update

# 2021-07-29T18:48:25 update

# 2021-08-25T12:46:58 update

# 2021-09-09T16:27:13 update

# 2021-12-16T12:05:30 update

# 2022-05-07T14:05:12 update

# 2022-07-18T20:52:29 update

# 2022-07-31T18:42:26 update

# 2022-09-09T13:10:08 update

# 2023-01-04T15:16:57 update

# 2023-01-17T14:49:04 update

# 2023-02-15T13:51:30 update

# 2023-03-08T09:15:53 update

# 2023-03-23T16:32:20 update

# 2023-03-28T09:32:01 update

# 2023-05-05T17:28:22 update

# 2023-06-01T08:13:52 update

# 2023-06-20T09:58:10 update

# 2023-07-04T16:14:34 update

# 2023-07-17T20:49:40 update

# 2023-12-26T11:49:18 update

# 2024-05-27T11:00:06 update

# 2024-07-04T08:53:03 update

# 2024-07-18T16:19:02 update

# 2024-08-07T09:35:35 update

# 2024-08-22T14:32:14 update

# 2025-05-20T14:19:23 update

# 2025-07-17T17:54:48 update

# 2025-07-28T13:06:30 update

# 2025-12-22T19:05:25 update

# 2026-01-08T18:43:02 update

# 2026-01-12T16:53:28 update

# 2026-04-16T16:58:23 update
