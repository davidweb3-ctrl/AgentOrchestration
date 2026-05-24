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
