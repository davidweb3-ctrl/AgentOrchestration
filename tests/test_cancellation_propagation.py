"""Test for cancellation propagation invariant.

Related to Issue #1128: [ Bounty $5k ] [ Orchestrator ] Avoid child retry after parent cancel
"""

import asyncio
import time
import pytest
from src.orchestrator.scheduler import TaskScheduler


class TestCancellationPropagation:
    """Test suite for cancellation propagation invariant."""

    def test_parent_cancellation_prevents_child_retry(self):
        """Core test: parent cancelled → child not retried."""
        scheduler = TaskScheduler()
        
        parent_id = scheduler.enqueue({"name": "parent"}, queue="test")
        child_id = scheduler.enqueue({"name": "child"}, queue="test", parent_id=parent_id)
        
        async def simulate():
            parent = await scheduler.dequeue(queue="test")
            child = await scheduler.dequeue(queue="test")
            
            # Cancel parent
            scheduler.cancel_parent(parent_id)
            
            # Child should not retry
            result = scheduler.fail(child["id"], queue="test")
            assert result is False
            assert child.get("retry_rejected_reason") == "parent_cancelled"
        
        asyncio.run(simulate())

    def test_parent_lifecycle_cancellation(self):
        """Test parent lifecycle state blocks child retry."""
        scheduler = TaskScheduler()
        
        child_id = scheduler.enqueue({"name": "child"}, queue="test", parent_id="parent-1")
        
        async def simulate():
            child = await scheduler.dequeue(queue="test")
            
            # Parent lifecycle cancelled
            result = scheduler.fail(child["id"], queue="test", parent_lifecycle="cancelled")
            assert result is False
            assert child.get("retry_rejected_reason") == "parent_cancelled"
        
        asyncio.run(simulate())

    def test_stale_attempt_detection(self):
        """Test stale attempt signals are rejected."""
        scheduler = TaskScheduler()
        
        task_id = scheduler.enqueue({"name": "test", "attempt": 5}, queue="test")
        
        async def simulate():
            task = await scheduler.dequeue(queue="test")
            assert task["attempt"] == 5
            
            # Stale attempt should be rejected immediately
            result = scheduler.fail(task_id, queue="test", expected_attempt=0)
            assert result is False
            # Check audit log for the rejection
            assert len(scheduler.retry_audit_log) > 0
            assert scheduler.retry_audit_log[-1]["reason"] == "stale_attempt"
        
        asyncio.run(simulate())

    def test_stale_revision_detection(self):
        """Test stale revision signals are rejected."""
        scheduler = TaskScheduler()
        
        task_id = scheduler.enqueue({"name": "test", "revision": 3}, queue="test")
        
        async def simulate():
            task = await scheduler.dequeue(queue="test")
            assert task["revision"] == 3
            
            # Stale revision should be rejected
            result = scheduler.fail(task_id, queue="test", expected_revision=0)
            assert result is False
            assert scheduler.retry_audit_log[-1]["reason"] == "stale_revision"
        
        asyncio.run(simulate())

    def test_normal_retry_works(self):
        """Test normal retry behavior is preserved."""
        scheduler = TaskScheduler()
        
        task_id = scheduler.enqueue({"name": "test"}, queue="test")
        
        async def simulate():
            task = await scheduler.dequeue(queue="test")
            assert task["retries"] == 0
            
            result = scheduler.fail(task_id, queue="test")
            assert result is True
            
            retried = await scheduler.dequeue(queue="test")
            assert retried["retries"] == 1
            assert retried["attempt"] == 1
        
        asyncio.run(simulate())

    def test_task_cancelled_not_retried(self):
        """Test cancelled tasks are not retried."""
        scheduler = TaskScheduler()
        
        task_id = scheduler.enqueue({"name": "test"}, queue="test")
        
        async def simulate():
            task = await scheduler.dequeue(queue="test")
            scheduler.cancel(task_id, reason="test")
            
            result = scheduler.fail(task_id, queue="test")
            assert result is False
        
        asyncio.run(simulate())

    def test_retry_audit_log(self):
        """Test retry decisions are audited."""
        scheduler = TaskScheduler(max_audit_log=5)
        
        task_id = scheduler.enqueue({"name": "test"}, queue="test")
        
        async def simulate():
            task = await scheduler.dequeue(queue="test")
            # Fail with stale attempt to trigger audit
            scheduler.fail(task_id, queue="test", expected_attempt=999)
            
            assert len(scheduler.retry_audit_log) > 0
            assert scheduler.retry_audit_log[-1]["decision"] == "rejected"
        
        asyncio.run(simulate())

    def test_bounded_audit_log(self):
        """Test audit log is bounded."""
        scheduler = TaskScheduler(max_audit_log=3)
        
        for i in range(5):
            task_id = scheduler.enqueue({"name": f"task_{i}"}, queue="test")
            scheduler.cancel(task_id, reason="test")
        
        assert len(scheduler.retry_audit_log) <= 3

    def test_is_lifecycle_cancelled_variants(self):
        """Test various cancellation lifecycle states."""
        scheduler = TaskScheduler()
        
        assert scheduler.is_lifecycle_cancelled("cancelled") is True
        assert scheduler.is_lifecycle_cancelled("canceled") is True
        assert scheduler.is_lifecycle_cancelled("cancelling") is True
        assert scheduler.is_lifecycle_cancelled("canceling") is True
        assert scheduler.is_lifecycle_cancelled("CANCELLED") is True
        assert scheduler.is_lifecycle_cancelled("running") is False
        assert scheduler.is_lifecycle_cancelled(None) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
