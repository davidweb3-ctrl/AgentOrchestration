"""Data lake governance - purpose limitation and destination validation."""

import json
from typing import Dict, Any, Optional, Set
from dataclasses import dataclass
from enum import Enum


class DataClass(Enum):
    """Data classification levels."""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


@dataclass
class DataLakeWrite:
    """Data lake write request with governance metadata."""
    purpose: str
    data_class: DataClass
    owner: str
    destination: str
    data: Any


class DataLakeGovernance:
    """Enforce purpose limitation in data lake writes."""
    
    def __init__(self, policy_registry: Optional[Dict] = None):
        self._policy_registry = policy_registry or self._default_policies()
        self._audit_log: list = []
    
    def _default_policies(self) -> Dict[str, Set[DataClass]]:
        """Default destination policies."""
        return {
            "analytics": {DataClass.PUBLIC, DataClass.INTERNAL},
            "reporting": {DataClass.PUBLIC, DataClass.INTERNAL, DataClass.CONFIDENTIAL},
            "ml_training": {DataClass.PUBLIC, DataClass.INTERNAL},
            "archive": {DataClass.PUBLIC, DataClass.INTERNAL, DataClass.CONFIDENTIAL, DataClass.RESTRICTED},
        }
    
    def validate_write(self, write: DataLakeWrite) -> bool:
        """
        Validate data lake write against governance policies.
        
        Returns True if write is allowed, False otherwise.
        """
        # Check required fields
        if not all([write.purpose, write.data_class, write.owner, write.destination]):
            self._audit_log.append({
                "action": "reject",
                "reason": "missing_required_fields",
                "write": self._serialize_write(write)
            })
            return False
        
        # Check destination policy
        allowed_classes = self._policy_registry.get(write.destination, set())
        if write.data_class not in allowed_classes:
            self._audit_log.append({
                "action": "reject",
                "reason": "destination_policy_violation",
                "destination": write.destination,
                "data_class": write.data_class.value,
                "allowed_classes": [c.value for c in allowed_classes],
                "owner": write.owner,
                "purpose": write.purpose
            })
            return False
        
        # Write is valid
        self._audit_log.append({
            "action": "allow",
            "destination": write.destination,
            "data_class": write.data_class.value,
            "owner": write.owner,
            "purpose": write.purpose
        })
        return True
    
    def _serialize_write(self, write: DataLakeWrite) -> Dict:
        """Serialize write for audit logging."""
        return {
            "purpose": write.purpose,
            "data_class": write.data_class.value if write.data_class else None,
            "owner": write.owner,
            "destination": write.destination
        }
    
    def get_audit_report(self, filter_by_purpose: Optional[str] = None, 
                        filter_by_owner: Optional[str] = None) -> list:
        """Get audit report with optional filtering."""
        filtered = self._audit_log
        
        if filter_by_purpose:
            filtered = [entry for entry in filtered 
                       if entry.get("purpose") == filter_by_purpose]
        
        if filter_by_owner:
            filtered = [entry for entry in filtered 
                       if entry.get("owner") == filter_by_owner]
        
        return filtered
    
    def add_destination_policy(self, destination: str, 
                              allowed_classes: Set[DataClass]) -> None:
        """Add or update destination policy."""
        self._policy_registry[destination] = allowed_classes


class DataLakeIngestionPipeline:
    """Data lake ingestion pipeline with governance enforcement."""
    
    def __init__(self, governance: Optional[DataLakeGovernance] = None):
        self._governance = governance or DataLakeGovernance()
        self._ingested_data: Dict[str, Any] = {}
    
    def ingest(self, data: Any, purpose: str, data_class: str, 
               owner: str, destination: str) -> bool:
        """
        Ingest data into lake with governance validation.
        
        Returns True if ingestion succeeds, False if rejected by governance.
        """
        try:
            data_class_enum = DataClass(data_class.lower())
        except ValueError:
            # Invalid data class
            return False
        
        write = DataLakeWrite(
            purpose=purpose,
            data_class=data_class_enum,
            owner=owner,
            destination=destination,
            data=data
        )
        
        if not self._governance.validate_write(write):
            return False
        
        # Ingest data
        key = f"{destination}/{owner}/{purpose}"
        self._ingested_data[key] = {
            "data": data,
            "metadata": {
                "purpose": purpose,
                "data_class": data_class,
                "owner": owner,
                "destination": destination
            }
        }
        
        return True
    
    def get_governance(self) -> DataLakeGovernance:
        """Get governance instance for audit reporting."""
        return self._governance
