"""Test for cancellation propagation invariant.

Related to Issue #1128: [ Bounty $5k ] [ Orchestrator ] Avoid child retry after parent cancel
"""

import asyncio
import pytest

from src.orchestrator import scheduler as scheduler_module
from src.orchestrator.scheduler import CANCELLED_LIFECYCLES, TaskScheduler


AUDIT_KEYS = {
    "decision",
    "reason",
    "task_id",
    "parent_id",
    "attempt",
    "revision",
    "lifecycle_state",
    "parent_attempt",
    "parent_revision",
    "parent_lifecycle_state",
}


class TestCancellationPropagation:
    """Test suite for cancellation propagation invariant."""

    def setup_method(self):
        self.scheduler = TaskScheduler()

    def dequeue(self):
        return asyncio.run(self.scheduler.dequeue())

    def assert_sanitized_audit(self, audit):
        assert set(audit) == AUDIT_KEYS
        assert audit["decision"] == "retry_rejected"
        assert "payload" not in audit
        assert "config" not in audit
        assert "secret" not in audit
        assert "token" not in audit

    def test_parent_cancellation_prevents_child_retry(self):
        """Core test: parent cancelled → child not retried."""
        parent_id = self.scheduler.enqueue({"type": "parent"})
        parent = self.dequeue()
        assert parent["id"] == parent_id
        assert self.scheduler.cancel(parent_id)

        child_id = self.scheduler.enqueue({
            "type": "child",
            "parent_id": parent_id,
            "payload": {"token": "do-not-audit"},
        })
        child = self.dequeue()

        assert child["id"] == child_id
        assert not self.scheduler.fail(child_id)
        assert child["retries"] == 0
        assert self.dequeue() is None
        assert (
            self.scheduler.get_task_state(parent_id)["lifecycle_state"]
            == "cancelled"
        )
        assert (
            self.scheduler.get_task_state(child_id)["lifecycle_state"]
            == "cancelled"
        )

        audit = self.scheduler.retry_audit()[-1]
        self.assert_sanitized_audit(audit)
        assert audit["reason"] == "parent_cancelled"
        assert audit["task_id"] == child_id
        assert audit["parent_id"] == parent_id
        assert audit["parent_lifecycle_state"] == "cancelled"

    def test_parent_lifecycle_cancellation(self):
        """Test parent lifecycle state blocks child retry."""
        child_id = self.scheduler.enqueue({
            "type": "child",
            "parent_id": "parent-1",
        })
        child = self.dequeue()

        # Parent lifecycle cancelled
        result = self.scheduler.fail(child_id, parent_lifecycle="cancelled")
        assert result is False
        assert child.get("retry_rejected_reason") is None  # We don't set this anymore
        audit = self.scheduler.retry_audit()[-1]
        assert audit["reason"] == "parent_cancelled"

    def test_stale_attempt_detection(self):
        """Test stale attempt signals are rejected."""
        task_id = self.scheduler.enqueue({
            "type": "child",
            "attempt": 1,
            "revision": 3,
        })
        task = self.dequeue()

        assert not self.scheduler.fail(task_id, expected_attempt=2)
        assert task["retries"] == 0
        assert task["attempt"] == 1
        assert task["revision"] == 3
        assert (
            self.scheduler.get_task_state(task_id)["lifecycle_state"]
            == "running"
        )
        assert self.dequeue() is None

        audit = self.scheduler.retry_audit()[-1]
        self.assert_sanitized_audit(audit)
        assert audit["reason"] == "stale_child_attempt"
        assert audit["task_id"] == task_id
        assert audit["attempt"] == 1
        assert audit["revision"] == 3
        assert audit["lifecycle_state"] == "running"

    def test_stale_revision_detection(self):
        """Test stale revision signals are rejected."""
        task_id = self.scheduler.enqueue({
            "type": "child",
            "attempt": 1,
            "revision": 3,
        })
        task = self.dequeue()

        assert not self.scheduler.fail(task_id, expected_revision=9)
        assert task["retries"] == 0
        assert task["attempt"] == 1
        assert task["revision"] == 3

        audit = self.scheduler.retry_audit()[-1]
        assert audit["reason"] == "stale_child_revision"

    def test_normal_retry_works(self):
        """Test normal retry behavior is preserved."""
        task_id = self.scheduler.enqueue({"type": "test"})
        task = self.dequeue()
        assert task["retries"] == 0

        result = self.scheduler.fail(task_id)
        assert result is True

        retried = self.dequeue()
        assert retried["id"] == task_id
        assert retried["retries"] == 1
        assert retried["attempt"] == 1
        assert retried["revision"] == 1

    def test_task_cancelled_not_retried(self):
        """Test cancelled tasks are not retried."""
        task_id = self.scheduler.enqueue({"type": "test"})
        task = self.dequeue()
        assert self.scheduler.cancel(task_id)

        result = self.scheduler.fail(task_id)
        assert result is False

    def test_retry_audit_log(self):
        """Test retry decisions are audited."""
        task_id = self.scheduler.enqueue({
            "type": "child",
            "attempt": 1,
            "revision": 3,
        })
        self.dequeue()

        # Fail with stale attempt to trigger audit
        self.scheduler.fail(task_id, expected_attempt=999)

        assert len(self.scheduler.retry_audit()) > 0
        audit = self.scheduler.retry_audit()[-1]
        assert audit["decision"] == "retry_rejected"

    def test_bounded_audit_log(self):
        """Test audit log is bounded."""
        task_id = self.scheduler.enqueue({
            "type": "child",
            "payload": {"secret": "do-not-audit"},
        })
        self.dequeue()

        for _ in range(105):
            assert not self.scheduler.fail(task_id, expected_attempt=10)

        audit = self.scheduler.retry_audit()
        assert len(audit) == 100
        assert audit[-1]["reason"] == "stale_child_attempt"
        self.assert_sanitized_audit(audit[-1])

    def test_is_lifecycle_cancelled_variants(self):
        """Test various cancellation lifecycle states."""
        # These are static methods now, test via the class
        from src.orchestrator.scheduler import CANCELLED_LIFECYCLES

        assert "cancelled" in CANCELLED_LIFECYCLES
        assert "canceled" in CANCELLED_LIFECYCLES
        assert "cancelling" in CANCELLED_LIFECYCLES
        assert "canceling" in CANCELLED_LIFECYCLES

    def test_cancel_is_idempotent_and_audited_once(self):
        """Test cancel is idempotent and only audited once."""
        task_id = self.scheduler.enqueue({"type": "test"})
        task = self.dequeue()

        assert self.scheduler.cancel(task_id)
        after_first_cancel = self.scheduler.get_task_state(task_id)
        assert after_first_cancel["lifecycle_state"] == "cancelled"

        assert self.scheduler.cancel(task_id)
        assert self.scheduler.get_task_state(task_id) == after_first_cancel
        assert len(self.scheduler.cancel_audit()) == 1

    @pytest.mark.parametrize("lifecycle", sorted(CANCELLED_LIFECYCLES))
    def test_cancelled_lifecycle_cancel_is_a_noop(self, lifecycle):
        """Test cancelling an already cancelled task is a noop."""
        task_id = self.scheduler.enqueue({
            "type": "test",
            "lifecycle_state": lifecycle,
        })
        before = self.scheduler.get_task_state(task_id)

        assert self.scheduler.cancel(task_id)
        assert self.scheduler.get_task_state(task_id) == before
        assert self.scheduler.cancel_audit() == []

    def test_cancelled_ancestor_rejects_grandchild_retry(self):
        """Test cancelled ancestor rejects grandchild retry."""
        parent_id = self.scheduler.enqueue({"type": "parent"})
        parent = self.dequeue()
        assert parent["id"] == parent_id

        child_id = self.scheduler.enqueue({
            "type": "child",
            "parent_id": parent_id,
        })
        child = self.dequeue()
        assert child["id"] == child_id

        grandchild_id = self.scheduler.enqueue({
            "type": "grandchild",
            "parent_id": child_id,
            "payload": {"secret": "do-not-audit"},
        })
        grandchild = self.dequeue()
        assert grandchild["id"] == grandchild_id

        assert self.scheduler.cancel(parent_id)
        assert self.scheduler.cancel(child_id)
        assert not self.scheduler.fail(grandchild_id)
        assert self.dequeue() is None

        audit = self.scheduler.retry_audit()[-1]
        self.assert_sanitized_audit(audit)
        assert audit["reason"] == "ancestor_cancelled"
        assert audit["task_id"] == grandchild_id
        assert audit["parent_id"] == child_id
        assert audit["parent_lifecycle_state"] == "cancelled"

    @pytest.mark.parametrize(
        "task_snapshot, fail_snapshot",
        [
            ("cancelled", None),
            (None, "cancelling"),
        ],
    )
    def test_cancelled_parent_snapshot_rejects_child_retry(
        self,
        task_snapshot,
        fail_snapshot,
    ):
        """Test cancelled parent snapshot rejects child retry."""
        child = {
            "type": "child",
            "parent_id": "parent-from-snapshot",
        }
        if task_snapshot is not None:
            child["parent_lifecycle_state"] = task_snapshot
        child_id = self.scheduler.enqueue(child)
        child = self.dequeue()

        assert child["id"] == child_id
        assert not self.scheduler.fail(
            child_id,
            parent_lifecycle=fail_snapshot,
        )
        assert (
            self.scheduler.get_task_state(child_id)["lifecycle_state"]
            == "cancelled"
        )
        assert self.dequeue() is None

        audit = self.scheduler.retry_audit()[-1]
        self.assert_sanitized_audit(audit)
        assert audit["reason"] == "parent_cancelled"
        assert audit["parent_id"] == "parent-from-snapshot"
        assert audit["parent_lifecycle_state"] == (
            task_snapshot or fail_snapshot
        )

    def test_stale_parent_revision_rejects_without_incrementing_retries(self):
        """Test stale parent revision rejects without incrementing retries."""
        parent_id = self.scheduler.enqueue({"type": "parent"})
        parent = self.dequeue()
        assert self.scheduler.complete(parent["id"])

        child_id = self.scheduler.enqueue({
            "type": "child",
            "parent_id": parent_id,
            "parent_revision": 4,
        })
        child = self.dequeue()

        assert not self.scheduler.fail(child_id)
        assert child["retries"] == 0
        assert (
            self.scheduler.get_task_state(child_id)["lifecycle_state"]
            == "running"
        )
        assert self.dequeue() is None

        audit = self.scheduler.retry_audit()[-1]
        self.assert_sanitized_audit(audit)
        assert audit["reason"] == "stale_parent_revision"
        assert audit["parent_id"] == parent_id
        assert audit["parent_revision"] == 4

    def test_scheduled_task_promotion_preserves_identity_queue_and_priority(
        self,
        monkeypatch,
    ):
        """Test scheduled task promotion preserves identity, queue and priority."""
        now = 1000.0
        monkeypatch.setattr(scheduler_module.time, "time", lambda: now)

        task_id = self.scheduler.schedule(
            {"id": "sched-task-001", "type": "scheduled"},
            delay=5,
            queue="high-priority",
            priority=1,
        )
        assert task_id == "sched-task-001"

        now = 1006.0
        task = asyncio.run(self.scheduler.dequeue(queue="high-priority"))

        assert task["id"] == "sched-task-001"
        assert task["queue"] == "high-priority"
        assert task["priority"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
