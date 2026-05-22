"""Tests for data retention exceptions and governance validation."""

import pytest
from datetime import date, datetime, timedelta
from src.governance.retention import (
    RetentionException,
    RetentionExceptionRegistry,
    GovernanceValidationError,
    RetentionExceptionReport,
)


class TestRetentionException:
    """Tests for RetentionException dataclass."""
    
    def test_create_valid_exception(self):
        """Test creating a valid retention exception."""
        future_date = date.today() + timedelta(days=30)
        review_date = date.today() + timedelta(days=15)
        
        exc = RetentionException(
            id="exc-001",
            owner="john.doe@example.com",
            reason="Legal hold for litigation case #12345",
            expiration=future_date,
            review_date=review_date,
            dataset="customer_pii",
        )
        
        assert exc.id == "exc-001"
        assert exc.owner == "john.doe@example.com"
        assert exc.reason == "Legal hold for litigation case #12345"
        assert exc.expiration == future_date
        assert exc.review_date == review_date
        assert exc.dataset == "customer_pii"
        assert exc.is_active() is True
        assert exc.is_expired() is False
    
    def test_exception_missing_owner_raises_error(self):
        """Test that missing owner raises GovernanceValidationError."""
        future_date = date.today() + timedelta(days=30)
        
        with pytest.raises(GovernanceValidationError, match="owner"):
            RetentionException(
                id="exc-002",
                owner="",
                reason="Valid reason",
                expiration=future_date,
                review_date=future_date,
            )
    
    def test_exception_whitespace_owner_raises_error(self):
        """Test that whitespace-only owner raises GovernanceValidationError."""
        future_date = date.today() + timedelta(days=30)
        
        with pytest.raises(GovernanceValidationError, match="owner"):
            RetentionException(
                id="exc-003",
                owner="   ",
                reason="Valid reason",
                expiration=future_date,
                review_date=future_date,
            )
    
    def test_exception_missing_reason_raises_error(self):
        """Test that missing reason raises GovernanceValidationError."""
        future_date = date.today() + timedelta(days=30)
        
        with pytest.raises(GovernanceValidationError, match="reason"):
            RetentionException(
                id="exc-004",
                owner="john.doe@example.com",
                reason="",
                expiration=future_date,
                review_date=future_date,
            )
    
    def test_exception_missing_expiration_raises_error(self):
        """Test that missing expiration raises GovernanceValidationError."""
        future_date = date.today() + timedelta(days=30)
        
        with pytest.raises(GovernanceValidationError, match="expiration"):
            RetentionException(
                id="exc-005",
                owner="john.doe@example.com",
                reason="Valid reason",
                expiration=None,  # type: ignore
                review_date=future_date,
            )
    
    def test_exception_missing_review_date_raises_error(self):
        """Test that missing review_date raises GovernanceValidationError."""
        future_date = date.today() + timedelta(days=30)
        
        with pytest.raises(GovernanceValidationError, match="review"):
            RetentionException(
                id="exc-006",
                owner="john.doe@example.com",
                reason="Valid reason",
                expiration=future_date,
                review_date=None,  # type: ignore
            )
    
    def test_expired_exception_detection(self):
        """Test that expired exceptions are correctly detected."""
        past_date = date.today() - timedelta(days=1)
        review_date = date.today() - timedelta(days=10)
        
        exc = RetentionException(
            id="exc-007",
            owner="jane.doe@example.com",
            reason="Expired exception",
            expiration=past_date,
            review_date=review_date,
        )
        
        assert exc.is_expired() is True
        assert exc.is_active() is False
    
    def test_to_dict_conversion(self):
        """Test conversion to dictionary."""
        future_date = date.today() + timedelta(days=30)
        review_date = date.today() + timedelta(days=15)
        
        exc = RetentionException(
            id="exc-008",
            owner="test@example.com",
            reason="Test reason",
            expiration=future_date,
            review_date=review_date,
            dataset="test_data",
        )
        
        data = exc.to_dict()
        
        assert data["id"] == "exc-008"
        assert data["owner"] == "test@example.com"
        assert data["reason"] == "Test reason"
        assert data["expiration"] == future_date.isoformat()
        assert data["review_date"] == review_date.isoformat()
        assert data["dataset"] == "test_data"
        assert "is_expired" in data
        assert data["is_expired"] is False


class TestRetentionExceptionRegistry:
    """Tests for RetentionExceptionRegistry."""
    
    def setup_method(self):
        self.registry = RetentionExceptionRegistry()
    
    def test_register_valid_exception(self):
        """Test registering a valid exception."""
        future_date = date.today() + timedelta(days=30)
        
        exc = RetentionException(
            id="exc-001",
            owner="owner1@example.com",
            reason="Test reason",
            expiration=future_date,
            review_date=future_date,
        )
        
        exc_id = self.registry.register(exc)
        assert exc_id == "exc-001"
        assert self.registry.get("exc-001") == exc
    
    def test_register_duplicate_id_raises_error(self):
        """Test that registering duplicate ID raises error."""
        future_date = date.today() + timedelta(days=30)
        
        exc1 = RetentionException(
            id="exc-dup",
            owner="owner1@example.com",
            reason="Reason 1",
            expiration=future_date,
            review_date=future_date,
        )
        
        exc2 = RetentionException(
            id="exc-dup",
            owner="owner2@example.com",
            reason="Reason 2",
            expiration=future_date,
            review_date=future_date,
        )
        
        self.registry.register(exc1)
        
        with pytest.raises(GovernanceValidationError, match="already exists"):
            self.registry.register(exc2)
    
    def test_get_nonexistent_exception(self):
        """Test getting a non-existent exception returns None."""
        result = self.registry.get("nonexistent")
        assert result is None
    
    def test_list_all_exceptions(self):
        """Test listing all exceptions."""
        future_date = date.today() + timedelta(days=30)
        
        for i in range(3):
            exc = RetentionException(
                id=f"exc-{i}",
                owner=f"owner{i}@example.com",
                reason=f"Reason {i}",
                expiration=future_date,
                review_date=future_date,
            )
            self.registry.register(exc)
        
        all_exceptions = self.registry.list_all()
        assert len(all_exceptions) == 3
    
    def test_list_active_exceptions(self):
        """Test listing only active exceptions."""
        future_date = date.today() + timedelta(days=30)
        past_date = date.today() - timedelta(days=1)
        
        # Active exception
        active_exc = RetentionException(
            id="exc-active",
            owner="active@example.com",
            reason="Active reason",
            expiration=future_date,
            review_date=future_date,
        )
        
        # Expired exception
        expired_exc = RetentionException(
            id="exc-expired",
            owner="expired@example.com",
            reason="Expired reason",
            expiration=past_date,
            review_date=past_date - timedelta(days=10),
        )
        
        self.registry.register(active_exc)
        self.registry.register(expired_exc)
        
        active = self.registry.list_active()
        assert len(active) == 1
        assert active[0].id == "exc-active"
    
    def test_list_expired_exceptions(self):
        """Test listing only expired exceptions."""
        future_date = date.today() + timedelta(days=30)
        past_date = date.today() - timedelta(days=1)
        
        active_exc = RetentionException(
            id="exc-active",
            owner="active@example.com",
            reason="Active reason",
            expiration=future_date,
            review_date=future_date,
        )
        
        expired_exc = RetentionException(
            id="exc-expired",
            owner="expired@example.com",
            reason="Expired reason",
            expiration=past_date,
            review_date=past_date - timedelta(days=10),
        )
        
        self.registry.register(active_exc)
        self.registry.register(expired_exc)
        
        expired = self.registry.list_expired()
        assert len(expired) == 1
        assert expired[0].id == "exc-expired"
    
    def test_delete_exception(self):
        """Test deleting an exception."""
        future_date = date.today() + timedelta(days=30)
        
        exc = RetentionException(
            id="exc-delete",
            owner="delete@example.com",
            reason="To be deleted",
            expiration=future_date,
            review_date=future_date,
        )
        
        self.registry.register(exc)
        assert self.registry.get("exc-delete") is not None
        
        result = self.registry.delete("exc-delete")
        assert result is True
        assert self.registry.get("exc-delete") is None
    
    def test_delete_nonexistent_exception(self):
        """Test deleting a non-existent exception returns False."""
        result = self.registry.delete("nonexistent")
        assert result is False
    
    def test_validate_all_with_expired_exceptions(self):
        """Test validation catches expired exceptions."""
        past_date = date.today() - timedelta(days=5)
        
        expired_exc = RetentionException(
            id="exc-expired",
            owner="expired@example.com",
            reason="Expired reason",
            expiration=past_date,
            review_date=past_date - timedelta(days=10),
        )
        
        self.registry.register(expired_exc)
        
        violations = self.registry.validate_all()
        assert len(violations) == 1
        assert violations[0]["exception_id"] == "exc-expired"
        assert violations[0]["owner"] == "expired@example.com"
        assert "expired" in violations[0]["error"].lower()
    
    def test_validate_all_no_violations(self):
        """Test validation passes with no expired exceptions."""
        future_date = date.today() + timedelta(days=30)
        
        exc = RetentionException(
            id="exc-valid",
            owner="valid@example.com",
            reason="Valid reason",
            expiration=future_date,
            review_date=future_date,
        )
        
        self.registry.register(exc)
        
        violations = self.registry.validate_all()
        assert len(violations) == 0
    
    def test_group_by_owner(self):
        """Test grouping exceptions by owner."""
        future_date = date.today() + timedelta(days=30)
        
        # Create exceptions for two different owners
        exc1 = RetentionException(
            id="exc-owner1-1",
            owner="owner1@example.com",
            reason="Reason 1",
            expiration=future_date,
            review_date=future_date,
        )
        
        exc2 = RetentionException(
            id="exc-owner1-2",
            owner="owner1@example.com",
            reason="Reason 2",
            expiration=future_date,
            review_date=future_date,
        )
        
        exc3 = RetentionException(
            id="exc-owner2-1",
            owner="owner2@example.com",
            reason="Reason 3",
            expiration=future_date,
            review_date=future_date,
        )
        
        self.registry.register(exc1)
        self.registry.register(exc2)
        self.registry.register(exc3)
        
        grouped = self.registry.group_by_owner()
        
        assert len(grouped) == 2
        assert len(grouped["owner1@example.com"]) == 2
        assert len(grouped["owner2@example.com"]) == 1
    
    def test_group_by_owner_active_only(self):
        """Test grouping only active exceptions by owner."""
        future_date = date.today() + timedelta(days=30)
        past_date = date.today() - timedelta(days=1)
        
        # Active exception
        active_exc = RetentionException(
            id="exc-active",
            owner="owner@example.com",
            reason="Active",
            expiration=future_date,
            review_date=future_date,
        )
        
        # Expired exception
        expired_exc = RetentionException(
            id="exc-expired",
            owner="owner@example.com",
            reason="Expired",
            expiration=past_date,
            review_date=past_date - timedelta(days=10),
        )
        
        self.registry.register(active_exc)
        self.registry.register(expired_exc)
        
        # All exceptions grouped
        all_grouped = self.registry.group_by_owner(active_only=False)
        assert len(all_grouped["owner@example.com"]) == 2
        
        # Only active grouped
        active_grouped = self.registry.group_by_owner(active_only=True)
        assert len(active_grouped["owner@example.com"]) == 1


class TestRetentionExceptionReport:
    """Tests for RetentionExceptionReport."""
    
    def setup_method(self):
        self.registry = RetentionExceptionRegistry()
    
    def test_generate_report_structure(self):
        """Test report generation produces correct structure."""
        future_date = date.today() + timedelta(days=30)
        
        exc = RetentionException(
            id="exc-001",
            owner="report@example.com",
            reason="Report test",
            expiration=future_date,
            review_date=future_date,
            dataset="test_dataset",
        )
        
        self.registry.register(exc)
        
        report_gen = RetentionExceptionReport(registry=self.registry)
        report = report_gen.generate()
        
        assert "generated_at" in report
        assert "as_of" in report
        assert "summary" in report
        assert "active_by_owner" in report
        assert "expired_exceptions" in report
        assert "violations" in report
    
    def test_report_summary_counts(self):
        """Test report summary contains correct counts."""
        future_date = date.today() + timedelta(days=30)
        past_date = date.today() - timedelta(days=1)
        
        # Active exception
        active_exc = RetentionException(
            id="exc-active",
            owner="owner@example.com",
            reason="Active",
            expiration=future_date,
            review_date=future_date,
        )
        
        # Expired exception
        expired_exc = RetentionException(
            id="exc-expired",
            owner="owner@example.com",
            reason="Expired",
            expiration=past_date,
            review_date=past_date - timedelta(days=10),
        )
        
        self.registry.register(active_exc)
        self.registry.register(expired_exc)
        
        report_gen = RetentionExceptionReport(registry=self.registry)
        report = report_gen.generate()
        
        summary = report["summary"]
        assert summary["total_exceptions"] == 2
        assert summary["active_exceptions"] == 1
        assert summary["expired_exceptions"] == 1
        assert summary["unique_owners"] == 1
        assert summary["validation_violations"] == 1
    
    def test_report_active_by_owner(self):
        """Test report groups active exceptions by owner."""
        future_date = date.today() + timedelta(days=30)
        
        exc1 = RetentionException(
            id="exc-001",
            owner="owner1@example.com",
            reason="Reason 1",
            expiration=future_date,
            review_date=future_date,
        )
        
        exc2 = RetentionException(
            id="exc-002",
            owner="owner2@example.com",
            reason="Reason 2",
            expiration=future_date,
            review_date=future_date,
        )
        
        self.registry.register(exc1)
        self.registry.register(exc2)
        
        report_gen = RetentionExceptionReport(registry=self.registry)
        report = report_gen.generate()
        
        active_by_owner = report["active_by_owner"]
        assert "owner1@example.com" in active_by_owner
        assert "owner2@example.com" in active_by_owner
        assert len(active_by_owner["owner1@example.com"]) == 1
        assert len(active_by_owner["owner2@example.com"]) == 1
    
    def test_report_expired_exceptions_list(self):
        """Test report includes expired exceptions."""
        past_date = date.today() - timedelta(days=5)
        
        expired_exc = RetentionException(
            id="exc-expired",
            owner="expired@example.com",
            reason="Expired",
            expiration=past_date,
            review_date=past_date - timedelta(days=10),
        )
        
        self.registry.register(expired_exc)
        
        report_gen = RetentionExceptionReport(registry=self.registry)
        report = report_gen.generate()
        
        assert len(report["expired_exceptions"]) == 1
        assert report["expired_exceptions"][0]["id"] == "exc-expired"
        assert report["expired_exceptions"][0]["is_expired"] is True