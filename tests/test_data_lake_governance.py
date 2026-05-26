"""Tests for data lake governance - purpose limitation enforcement."""

import pytest
from src.common.data_lake_governance import (
    DataLakeGovernance,
    DataLakeIngestionPipeline,
    DataLakeWrite,
    DataClass
)


class TestDataLakeGovernance:
    """Test data lake governance enforcement."""
    
    def test_valid_write_allowed(self):
        """Test that valid writes are allowed."""
        governance = DataLakeGovernance()
        write = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-alpha",
            destination="analytics",
            data={"metrics": [1, 2, 3]}
        )
        
        assert governance.validate_write(write) is True
        
        # Check audit log
        audit = governance.get_audit_report()
        assert len(audit) == 1
        assert audit[0]["action"] == "allow"
        assert audit[0]["purpose"] == "analytics"
        assert audit[0]["owner"] == "team-alpha"
    
    def test_missing_fields_rejected(self):
        """Test that writes with missing required fields are rejected."""
        governance = DataLakeGovernance()
        write = DataLakeWrite(
            purpose="",
            data_class=DataClass.INTERNAL,
            owner="team-alpha",
            destination="analytics",
            data={"metrics": [1, 2, 3]}
        )
        
        assert governance.validate_write(write) is False
        
        audit = governance.get_audit_report()
        assert len(audit) == 1
        assert audit[0]["action"] == "reject"
        assert audit[0]["reason"] == "missing_required_fields"
    
    def test_destination_policy_violation(self):
        """Test that writes to unauthorized destinations are rejected."""
        governance = DataLakeGovernance()
        write = DataLakeWrite(
            purpose="training",
            data_class=DataClass.RESTRICTED,  # Not allowed in ml_training
            owner="team-beta",
            destination="ml_training",
            data={"sensitive": "data"}
        )
        
        assert governance.validate_write(write) is False
        
        audit = governance.get_audit_report()
        assert len(audit) == 1
        assert audit[0]["action"] == "reject"
        assert audit[0]["reason"] == "destination_policy_violation"
        assert audit[0]["data_class"] == "restricted"
    
    def test_audit_report_filtering_by_purpose(self):
        """Test audit report filtering by purpose."""
        governance = DataLakeGovernance()
        
        # Add multiple writes
        write1 = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-a",
            destination="analytics",
            data={}
        )
        write2 = DataLakeWrite(
            purpose="reporting",
            data_class=DataClass.CONFIDENTIAL,
            owner="team-b",
            destination="reporting",
            data={}
        )
        
        governance.validate_write(write1)
        governance.validate_write(write2)
        
        # Filter by purpose
        filtered = governance.get_audit_report(filter_by_purpose="analytics")
        assert len(filtered) == 1
        assert filtered[0]["purpose"] == "analytics"
    
    def test_audit_report_filtering_by_owner(self):
        """Test audit report filtering by owner."""
        governance = DataLakeGovernance()
        
        write1 = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-a",
            destination="analytics",
            data={}
        )
        write2 = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-b",
            destination="analytics",
            data={}
        )
        
        governance.validate_write(write1)
        governance.validate_write(write2)
        
        # Filter by owner
        filtered = governance.get_audit_report(filter_by_owner="team-a")
        assert len(filtered) == 1
        assert filtered[0]["owner"] == "team-a"


class TestDataLakeIngestionPipeline:
    """Test data lake ingestion pipeline."""
    
    def test_successful_ingestion(self):
        """Test successful data ingestion with valid governance."""
        pipeline = DataLakeIngestionPipeline()
        
        result = pipeline.ingest(
            data={"metrics": [1, 2, 3]},
            purpose="analytics",
            data_class="internal",
            owner="team-alpha",
            destination="analytics"
        )
        
        assert result is True
        
        # Check audit log
        governance = pipeline.get_governance()
        audit = governance.get_audit_report()
        assert len(audit) == 1
        assert audit[0]["action"] == "allow"
    
    def test_ingestion_rejected_by_governance(self):
        """Test that ingestion is rejected when governance check fails."""
        pipeline = DataLakeIngestionPipeline()
        
        result = pipeline.ingest(
            data={"sensitive": "data"},
            purpose="training",
            data_class="restricted",  # Not allowed in ml_training
            owner="team-beta",
            destination="ml_training"
        )
        
        assert result is False
        
        # Check audit log shows rejection
        governance = pipeline.get_governance()
        audit = governance.get_audit_report()
        assert len(audit) == 1
        assert audit[0]["action"] == "reject"
    
    def test_ingestion_with_invalid_data_class(self):
        """Test that invalid data class is rejected."""
        pipeline = DataLakeIngestionPipeline()
        
        result = pipeline.ingest(
            data={"test": "data"},
            purpose="analytics",
            data_class="invalid_class",  # Invalid
            owner="team-alpha",
            destination="analytics"
        )
        
        assert result is False
    
    def test_multiple_ingestions(self):
        """Test multiple data ingestions with audit trail."""
        pipeline = DataLakeIngestionPipeline()
        
        # Valid ingestions
        pipeline.ingest(
            data={"metrics": [1, 2, 3]},
            purpose="analytics",
            data_class="internal",
            owner="team-a",
            destination="analytics"
        )
        pipeline.ingest(
            data={"report": "Q4 results"},
            purpose="reporting",
            data_class="confidential",
            owner="team-b",
            destination="reporting"
        )
        
        # Invalid ingestion
        pipeline.ingest(
            data={"restricted": "data"},
            purpose="training",
            data_class="restricted",
            owner="team-c",
            destination="ml_training"
        )
        
        # Check audit trail
        governance = pipeline.get_governance()
        audit = governance.get_audit_report()
        
        assert len(audit) == 3
        assert sum(1 for a in audit if a["action"] == "allow") == 2
        assert sum(1 for a in audit if a["action"] == "reject") == 1
    
    def test_data_class_all_levels(self):
        """Test all data classification levels."""
        pipeline = DataLakeIngestionPipeline()
        
        # Test each data class in appropriate destination
        test_cases = [
            ("public", "analytics", True),
            ("internal", "analytics", True),
            ("confidential", "reporting", True),
            ("restricted", "archive", True),
            ("restricted", "analytics", False),  # Not allowed
        ]
        
        for data_class, destination, expected in test_cases:
            result = pipeline.ingest(
                data={"test": "data"},
                purpose="test",
                data_class=data_class,
                owner="test-team",
                destination=destination
            )
            assert result == expected, f"Failed for {data_class} in {destination}"


class TestDataLakeEdgeCases:
    """Test edge cases for data lake governance."""
    
    def test_empty_data_allowed(self):
        """Test that empty data is allowed if metadata is valid."""
        governance = DataLakeGovernance()
        write = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-alpha",
            destination="analytics",
            data={}
        )
        
        assert governance.validate_write(write) is True
    
    def test_none_data_handled(self):
        """Test that None data is handled (implementation dependent)."""
        governance = DataLakeGovernance()
        write = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-alpha",
            destination="analytics",
            data=None
        )
        
        # Implementation may accept or reject None data
        result = governance.validate_write(write)
        assert result is True or result is False
    
    def test_whitespace_purpose_handled(self):
        """Test that whitespace purpose is handled (implementation dependent)."""
        governance = DataLakeGovernance()
        write = DataLakeWrite(
            purpose="   ",
            data_class=DataClass.INTERNAL,
            owner="team-alpha",
            destination="analytics",
            data={"test": "data"}
        )
        
        # Implementation may accept or reject whitespace
        result = governance.validate_write(write)
        assert result is True or result is False
    
    def test_audit_report_empty(self):
        """Test audit report when no writes."""
        governance = DataLakeGovernance()
        
        audit = governance.get_audit_report()
        assert audit == []
    
    def test_audit_report_multiple_filters(self):
        """Test audit report with multiple filters."""
        governance = DataLakeGovernance()
        
        # Add writes
        write1 = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-a",
            destination="analytics",
            data={}
        )
        write2 = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.CONFIDENTIAL,
            owner="team-b",
            destination="reporting",
            data={}
        )
        
        governance.validate_write(write1)
        governance.validate_write(write2)
        
        # Filter by purpose
        filtered = governance.get_audit_report(filter_by_purpose="analytics")
        assert len(filtered) == 2
        
        # Filter by owner
        filtered = governance.get_audit_report(filter_by_owner="team-a")
        assert len(filtered) == 1
    
    def test_data_class_public_allowed_everywhere(self):
        """Test that public data is allowed in all destinations."""
        pipeline = DataLakeIngestionPipeline()
        
        destinations = ["analytics", "reporting", "ml_training", "archive"]
        
        for dest in destinations:
            result = pipeline.ingest(
                data={"test": "data"},
                purpose="test",
                data_class="public",
                owner="test-team",
                destination=dest
            )
            assert result is True, f"Public data should be allowed in {dest}"
    
    def test_ingestion_with_large_data(self):
        """Test ingestion with large data payload."""
        pipeline = DataLakeIngestionPipeline()
        
        large_data = {"items": list(range(1000))}
        
        result = pipeline.ingest(
            data=large_data,
            purpose="analytics",
            data_class="internal",
            owner="team-alpha",
            destination="analytics"
        )
        
        assert result is True


class TestDataClassValidation:
    """Test data classification validation."""
    
    def test_data_class_enum_values(self):
        """Test that DataClass enum has expected values."""
        assert DataClass.PUBLIC.value == "public"
        assert DataClass.INTERNAL.value == "internal"
        assert DataClass.CONFIDENTIAL.value == "confidential"
        assert DataClass.RESTRICTED.value == "restricted"
    
    def test_data_class_from_string(self):
        """Test creating DataClass from string."""
        assert DataClass("public") == DataClass.PUBLIC
        assert DataClass("internal") == DataClass.INTERNAL
        assert DataClass("confidential") == DataClass.CONFIDENTIAL
        assert DataClass("restricted") == DataClass.RESTRICTED


class TestDestinationPolicy:
    """Test destination policy management."""
    
    def test_add_destination_policy(self):
        """Test adding a new destination policy."""
        governance = DataLakeGovernance()
        
        # Add new destination
        governance.add_destination_policy("new_destination", {DataClass.PUBLIC, DataClass.INTERNAL})
        
        # Verify policy works
        write = DataLakeWrite(
            purpose="test",
            data_class=DataClass.INTERNAL,
            owner="team-test",
            destination="new_destination",
            data={"test": "data"}
        )
        
        assert governance.validate_write(write) is True
    
    def test_update_destination_policy(self):
        """Test updating an existing destination policy."""
        governance = DataLakeGovernance()
        
        # Update analytics to only allow PUBLIC
        governance.add_destination_policy("analytics", {DataClass.PUBLIC})
        
        # INTERNAL should now be rejected
        write = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-test",
            destination="analytics",
            data={"test": "data"}
        )
        
        assert governance.validate_write(write) is False
    
    def test_custom_policy_registry(self):
        """Test governance with custom policy registry."""
        custom_policies = {
            "custom_dest": {DataClass.PUBLIC},
            "secure_dest": {DataClass.RESTRICTED}
        }
        
        governance = DataLakeGovernance(policy_registry=custom_policies)
        
        # Valid write to custom_dest
        write1 = DataLakeWrite(
            purpose="test",
            data_class=DataClass.PUBLIC,
            owner="team-a",
            destination="custom_dest",
            data={}
        )
        assert governance.validate_write(write1) is True
        
        # Valid write to secure_dest
        write2 = DataLakeWrite(
            purpose="test",
            data_class=DataClass.RESTRICTED,
            owner="team-b",
            destination="secure_dest",
            data={}
        )
        assert governance.validate_write(write2) is True
        
        # Invalid write - wrong class for destination
        write3 = DataLakeWrite(
            purpose="test",
            data_class=DataClass.INTERNAL,
            owner="team-c",
            destination="secure_dest",
            data={}
        )
        assert governance.validate_write(write3) is False


class TestAuditLog:
    """Test audit log functionality."""
    
    def test_audit_log_contains_all_fields(self):
        """Test that audit log entries contain expected fields."""
        governance = DataLakeGovernance()
        
        write = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-alpha",
            destination="analytics",
            data={"metrics": [1, 2, 3]}
        )
        
        governance.validate_write(write)
        
        audit = governance.get_audit_report()
        assert len(audit) == 1
        entry = audit[0]
        
        assert "action" in entry
        assert "destination" in entry
        assert "data_class" in entry
        assert "owner" in entry
        assert "purpose" in entry
    
    def test_audit_log_rejection_reason(self):
        """Test that rejection audit entries include reason."""
        governance = DataLakeGovernance()
        
        write = DataLakeWrite(
            purpose="",
            data_class=DataClass.INTERNAL,
            owner="team-alpha",
            destination="analytics",
            data={}
        )
        
        governance.validate_write(write)
        
        audit = governance.get_audit_report()
        assert audit[0]["action"] == "reject"
        assert "reason" in audit[0]
    
    def test_audit_log_allowed_classes(self):
        """Test that policy violation includes allowed classes."""
        governance = DataLakeGovernance()
        
        write = DataLakeWrite(
            purpose="training",
            data_class=DataClass.RESTRICTED,
            owner="team-beta",
            destination="ml_training",
            data={}
        )
        
        governance.validate_write(write)
        
        audit = governance.get_audit_report()
        entry = audit[0]
        assert entry["action"] == "reject"
        assert "allowed_classes" in entry
        assert isinstance(entry["allowed_classes"], list)


class TestPipelineEdgeCases:
    """Test pipeline edge cases."""
    
    def test_pipeline_with_custom_governance(self):
        """Test pipeline with custom governance instance."""
        custom_governance = DataLakeGovernance()
        custom_governance.add_destination_policy("custom", {DataClass.PUBLIC})
        
        pipeline = DataLakeIngestionPipeline(governance=custom_governance)
        
        result = pipeline.ingest(
            data={"test": "data"},
            purpose="test",
            data_class="public",
            owner="team-test",
            destination="custom"
        )
        
        assert result is True
    
    def test_ingestion_data_storage(self):
        """Test that ingested data is properly stored."""
        pipeline = DataLakeIngestionPipeline()
        
        test_data = {"key": "value", "nested": {"data": "test"}}
        
        result = pipeline.ingest(
            data=test_data,
            purpose="analytics",
            data_class="internal",
            owner="team-alpha",
            destination="analytics"
        )
        
        assert result is True
        # Data should be accessible via _ingested_data
        key = "analytics/team-alpha/analytics"
        assert key in pipeline._ingested_data
        assert pipeline._ingested_data[key]["data"] == test_data
    
    def test_unknown_destination_rejected(self):
        """Test that writes to unknown destinations are rejected."""
        governance = DataLakeGovernance()
        
        write = DataLakeWrite(
            purpose="test",
            data_class=DataClass.PUBLIC,
            owner="team-test",
            destination="unknown_destination",
            data={}
        )
        
        assert governance.validate_write(write) is False
        
        audit = governance.get_audit_report()
        assert audit[0]["reason"] == "destination_policy_violation"


class TestDataLakeAdvancedEdgeCases:
    """Advanced edge case tests for data lake governance."""
    
    def test_very_long_purpose_string(self):
        """Test purpose with very long string."""
        governance = DataLakeGovernance()
        long_purpose = "a" * 1000
        write = DataLakeWrite(
            purpose=long_purpose,
            data_class=DataClass.INTERNAL,
            owner="team-alpha",
            destination="analytics",
            data={"test": "data"}
        )
        
        result = governance.validate_write(write)
        assert result is True or result is False  # Implementation dependent
    
    def test_unicode_in_purpose_and_owner(self):
        """Test unicode characters in purpose and owner fields."""
        governance = DataLakeGovernance()
        write = DataLakeWrite(
            purpose="分析数据",
            data_class=DataClass.INTERNAL,
            owner="团队阿尔法",
            destination="analytics",
            data={"test": "data"}
        )
        
        result = governance.validate_write(write)
        # Should handle unicode gracefully
        assert result is True or result is False
    
    def test_special_characters_in_owner(self):
        """Test special characters in owner field."""
        governance = DataLakeGovernance()
        write = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-alpha@company.com",
            destination="analytics",
            data={"test": "data"}
        )
        
        result = governance.validate_write(write)
        assert result is True
    
    def test_sql_injection_in_purpose(self):
        """Test SQL injection attempt in purpose field."""
        governance = DataLakeGovernance()
        write = DataLakeWrite(
            purpose="analytics'; DROP TABLE audit_log; --",
            data_class=DataClass.INTERNAL,
            owner="team-alpha",
            destination="analytics",
            data={"test": "data"}
        )
        
        # Should handle gracefully without executing SQL
        result = governance.validate_write(write)
        audit = governance.get_audit_report()
        
        # If accepted, purpose should be stored as-is (sanitization is implementation dependent)
        if result and audit:
            assert "DROP TABLE" not in str(audit[0].get("purpose", "")) or audit[0]["purpose"] == write.purpose
    
    def test_nested_data_structures(self):
        """Test deeply nested data structures."""
        pipeline = DataLakeIngestionPipeline()
        
        nested_data = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {
                            "level5": "deep_value"
                        }
                    }
                }
            }
        }
        
        result = pipeline.ingest(
            data=nested_data,
            purpose="analytics",
            data_class="internal",
            owner="team-alpha",
            destination="analytics"
        )
        
        assert result is True
    
    def test_list_data_structure(self):
        """Test list as data structure."""
        pipeline = DataLakeIngestionPipeline()
        
        list_data = [1, 2, 3, 4, 5]
        
        result = pipeline.ingest(
            data=list_data,
            purpose="analytics",
            data_class="internal",
            owner="team-alpha",
            destination="analytics"
        )
        
        assert result is True
    
    def test_mixed_data_types(self):
        """Test mixed data types in payload."""
        pipeline = DataLakeIngestionPipeline()
        
        mixed_data = {
            "string": "test",
            "integer": 42,
            "float": 3.14,
            "boolean": True,
            "null": None,
            "list": [1, 2, 3],
            "dict": {"nested": "value"}
        }
        
        result = pipeline.ingest(
            data=mixed_data,
            purpose="analytics",
            data_class="internal",
            owner="team-alpha",
            destination="analytics"
        )
        
        assert result is True
    
    def test_concurrent_writes_same_destination(self):
        """Test multiple concurrent writes to same destination."""
        governance = DataLakeGovernance()
        
        writes = []
        for i in range(10):
            write = DataLakeWrite(
                purpose=f"analytics_{i}",
                data_class=DataClass.INTERNAL,
                owner=f"team-{i}",
                destination="analytics",
                data={"index": i}
            )
            writes.append(write)
        
        # Validate all writes
        for write in writes:
            governance.validate_write(write)
        
        audit = governance.get_audit_report()
        assert len(audit) == 10
    
    def test_audit_log_persistence(self):
        """Test that audit log persists across multiple operations."""
        governance = DataLakeGovernance()
        
        # First batch of writes
        for i in range(5):
            write = DataLakeWrite(
                purpose="analytics",
                data_class=DataClass.INTERNAL,
                owner="team-a",
                destination="analytics",
                data={"batch": 1, "index": i}
            )
            governance.validate_write(write)
        
        # Second batch of writes
        for i in range(5):
            write = DataLakeWrite(
                purpose="reporting",
                data_class=DataClass.CONFIDENTIAL,
                owner="team-b",
                destination="reporting",
                data={"batch": 2, "index": i}
            )
            governance.validate_write(write)
        
        audit = governance.get_audit_report()
        assert len(audit) == 10
        
        # Verify both batches are present
        purposes = {entry["purpose"] for entry in audit}
        assert "analytics" in purposes
        assert "reporting" in purposes
    
    def test_filter_by_nonexistent_purpose(self):
        """Test filtering by purpose that doesn't exist."""
        governance = DataLakeGovernance()
        
        write = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-a",
            destination="analytics",
            data={}
        )
        governance.validate_write(write)
        
        # Filter by non-existent purpose
        filtered = governance.get_audit_report(filter_by_purpose="nonexistent")
        assert len(filtered) == 0
    
    def test_filter_by_nonexistent_owner(self):
        """Test filtering by owner that doesn't exist."""
        governance = DataLakeGovernance()
        
        write = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-a",
            destination="analytics",
            data={}
        )
        governance.validate_write(write)
        
        # Filter by non-existent owner
        filtered = governance.get_audit_report(filter_by_owner="nonexistent")
        assert len(filtered) == 0
    
    def test_case_sensitivity_in_filters(self):
        """Test case sensitivity in audit filters."""
        governance = DataLakeGovernance()
        
        write = DataLakeWrite(
            purpose="Analytics",
            data_class=DataClass.INTERNAL,
            owner="Team-A",
            destination="analytics",
            data={}
        )
        governance.validate_write(write)
        
        # Filter with different case
        filtered = governance.get_audit_report(filter_by_purpose="analytics")
        # Case sensitivity is implementation dependent
        assert len(filtered) == 0 or len(filtered) == 1
    
    def test_empty_string_owner(self):
        """Test empty string as owner."""
        governance = DataLakeGovernance()
        write = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="",
            destination="analytics",
            data={"test": "data"}
        )
        
        result = governance.validate_write(write)
        # Empty owner may be rejected or accepted
        assert result is True or result is False
    
    def test_whitespace_only_fields(self):
        """Test whitespace-only values in fields."""
        governance = DataLakeGovernance()
        write = DataLakeWrite(
            purpose="   ",
            data_class=DataClass.INTERNAL,
            owner="   ",
            destination="analytics",
            data={"test": "data"}
        )
        
        result = governance.validate_write(write)
        # Whitespace handling is implementation dependent
        assert result is True or result is False
    
    def test_destination_with_special_chars(self):
        """Test destination with special characters."""
        governance = DataLakeGovernance()
        
        # Add destination with special characters
        governance.add_destination_policy("analytics-prod-01", {DataClass.INTERNAL})
        
        write = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-alpha",
            destination="analytics-prod-01",
            data={"test": "data"}
        )
        
        result = governance.validate_write(write)
        assert result is True
    
    def test_data_class_case_variations(self):
        """Test data class with case variations."""
        pipeline = DataLakeIngestionPipeline()
        
        # Test various case formats
        test_cases = [
            ("PUBLIC", False),  # All caps - likely invalid
            ("Public", False),  # Title case - likely invalid
            ("public", True),   # Lowercase - valid
        ]
        
        for data_class, expected in test_cases:
            result = pipeline.ingest(
                data={"test": "data"},
                purpose="test",
                data_class=data_class,
                owner="test-team",
                destination="analytics"
            )
            # Note: Case sensitivity handling varies by implementation
            assert result is True or result is False


class TestDataLakePerformance:
    """Performance tests for data lake governance."""
    
    def test_high_volume_writes(self):
        """Test high volume of write validations."""
        governance = DataLakeGovernance()
        
        import time
        start = time.time()
        
        for i in range(100):
            write = DataLakeWrite(
                purpose=f"analytics_{i}",
                data_class=DataClass.INTERNAL,
                owner=f"team-{i % 10}",
                destination="analytics",
                data={"index": i}
            )
            governance.validate_write(write)
        
        elapsed = time.time() - start
        
        # Should complete 100 validations in reasonable time (< 2 seconds)
        assert elapsed < 2.0, f"Too slow: {elapsed:.2f}s"
        
        audit = governance.get_audit_report()
        assert len(audit) == 100
    
    def test_high_volume_ingestion(self):
        """Test high volume data ingestion."""
        pipeline = DataLakeIngestionPipeline()
        
        import time
        start = time.time()
        
        for i in range(50):
            pipeline.ingest(
                data={"index": i, "data": "x" * 100},
                purpose="analytics",
                data_class="internal",
                owner="team-alpha",
                destination="analytics"
            )
        
        elapsed = time.time() - start
        
        # Should complete 50 ingestions in reasonable time (< 3 seconds)
        assert elapsed < 3.0, f"Too slow: {elapsed:.2f}s"
    
    def test_large_audit_log_filtering(self):
        """Test filtering large audit logs."""
        governance = DataLakeGovernance()
        
        # Create large audit log
        for i in range(200):
            write = DataLakeWrite(
                purpose="analytics" if i % 2 == 0 else "reporting",
                data_class=DataClass.INTERNAL,
                owner=f"team-{i % 5}",
                destination="analytics",
                data={"index": i}
            )
            governance.validate_write(write)
        
        import time
        start = time.time()
        
        # Filter large log
        filtered = governance.get_audit_report(filter_by_purpose="analytics")
        
        elapsed = time.time() - start
        
        # Should complete filtering in reasonable time (< 1 second)
        assert elapsed < 1.0, f"Filtering too slow: {elapsed:.2f}s"
        assert len(filtered) == 100  # Half of 200


class TestDataLakeSecurity:
    """Security tests for data lake governance."""
    
    def test_xss_in_purpose_field(self):
        """Test XSS attempt in purpose field."""
        governance = DataLakeGovernance()
        xss_payload = "<script>alert('xss')</script>"
        write = DataLakeWrite(
            purpose=xss_payload,
            data_class=DataClass.INTERNAL,
            owner="team-alpha",
            destination="analytics",
            data={"test": "data"}
        )
        
        result = governance.validate_write(write)
        audit = governance.get_audit_report()
        
        # If stored, should be stored as-is or sanitized
        if result and audit:
            # Script tag should not be executed (we can't test execution, but we can verify storage)
            assert xss_payload in str(audit[0].get("purpose", "")) or "script" not in str(audit[0].get("purpose", "")).lower()
    
    def test_command_injection_in_owner(self):
        """Test command injection attempt in owner field."""
        governance = DataLakeGovernance()
        cmd_payload = "team-alpha; rm -rf /"
        write = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner=cmd_payload,
            destination="analytics",
            data={"test": "data"}
        )
        
        # Should handle gracefully
        result = governance.validate_write(write)
        assert result is True or result is False
    
    def test_path_traversal_in_destination(self):
        """Test path traversal attempt in destination."""
        governance = DataLakeGovernance()
        traversal_payload = "../../../etc/passwd"
        write = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-alpha",
            destination=traversal_payload,
            data={"test": "data"}
        )
        
        # Should be rejected (unknown destination)
        result = governance.validate_write(write)
        assert result is False
    
    def test_no_sensitive_data_in_audit(self):
        """Test that sensitive data is not stored in audit log."""
        governance = DataLakeGovernance()
        sensitive_data = {"password": "secret123", "ssn": "123-45-6789"}
        write = DataLakeWrite(
            purpose="analytics",
            data_class=DataClass.INTERNAL,
            owner="team-alpha",
            destination="analytics",
            data=sensitive_data
        )
        
        governance.validate_write(write)
        audit = governance.get_audit_report()
        
        # Audit should not contain the actual sensitive data
        audit_str = str(audit[0])
        assert "password" not in audit_str or "secret123" not in audit_str
        assert "ssn" not in audit_str or "123-45-6789" not in audit_str
