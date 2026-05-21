"""Redaction policy for data exports - ensures consistent field masking across formats."""

from typing import Dict, Any, List, Optional, Set
from enum import Enum
from dataclasses import dataclass
import json


class FieldSensitivity(Enum):
    """Field sensitivity levels for redaction."""
    PUBLIC = "public"           # No redaction
    INTERNAL = "internal"       # Mask in external exports
    CONFIDENTIAL = "confidential"  # Mask in all exports except admin
    RESTRICTED = "restricted"   # Never export, UI only


@dataclass
class RedactionRule:
    """Redaction rule for a field."""
    field_path: str
    sensitivity: FieldSensitivity
    mask_value: Any = None


class RedactionPolicy:
    """Shared redaction policy for all export formats."""
    
    def __init__(self):
        self._rules: Dict[str, RedactionRule] = {}
        self._default_sensitivity = FieldSensitivity.PUBLIC
    
    def add_rule(self, field_path: str, sensitivity: FieldSensitivity, 
                 mask_value: Any = None) -> None:
        """Add a redaction rule for a field path."""
        self._rules[field_path] = RedactionRule(
            field_path=field_path,
            sensitivity=sensitivity,
            mask_value=mask_value
        )
    
    def redact(self, data: Dict[str, Any], export_format: str = "json",
               user_role: str = "user") -> Dict[str, Any]:
        """
        Apply redaction to data based on export format and user role.
        
        Args:
            data: The data to redact
            export_format: Target format (json, csv, ui)
            user_role: User role (user, admin)
        
        Returns:
            Redacted data copy
        """
        result = self._deep_copy(data)
        
        for field_path, rule in self._rules.items():
            if self._should_redact(rule, export_format, user_role):
                self._apply_redaction(result, field_path, rule.mask_value)
        
        return result
    
    def _should_redact(self, rule: RedactionRule, export_format: str,
                      user_role: str) -> bool:
        """Determine if a field should be redacted."""
        # Admin users see everything
        if user_role == "admin":
            return False
        
        sensitivity = rule.sensitivity
        
        # RESTRICTED fields are never exported
        if sensitivity == FieldSensitivity.RESTRICTED:
            return True
        
        # CONFIDENTIAL fields are masked in all exports
        if sensitivity == FieldSensitivity.CONFIDENTIAL:
            return True
        
        # INTERNAL fields are masked in JSON/CSV exports
        if sensitivity == FieldSensitivity.INTERNAL:
            if export_format in ["json", "csv"]:
                return True
        
        return False
    
    def _apply_redaction(self, data: Dict[str, Any], field_path: str,
                        mask_value: Any) -> None:
        """Apply redaction to a field in data."""
        parts = field_path.split(".")
        current = data
        
        for part in parts[:-1]:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return  # Path doesn't exist
        
        final_field = parts[-1]
        if isinstance(current, dict) and final_field in current:
            current[final_field] = mask_value if mask_value is not None else "***REDACTED***"
    
    def _deep_copy(self, data: Any) -> Any:
        """Create a deep copy of data."""
        return json.loads(json.dumps(data))
    
    def get_policy_summary(self) -> Dict[str, str]:
        """Get summary of redaction policy."""
        return {
            field_path: rule.sensitivity.value
            for field_path, rule in self._rules.items()
        }


class JSONExportSerializer:
    """JSON export serializer with redaction policy."""
    
    def __init__(self, policy: Optional[RedactionPolicy] = None):
        self._policy = policy or RedactionPolicy()
    
    def serialize(self, data: Dict[str, Any], user_role: str = "user") -> str:
        """
        Serialize data to JSON with redaction applied.
        
        Args:
            data: Data to serialize
            user_role: User role for redaction decisions
        
        Returns:
            JSON string with redacted fields
        """
        redacted_data = self._policy.redact(data, "json", user_role)
        return json.dumps(redacted_data, indent=2)
    
    def get_policy(self) -> RedactionPolicy:
        """Get the redaction policy."""
        return self._policy


class CSVExportSerializer:
    """CSV export serializer with redaction policy."""
    
    def __init__(self, policy: Optional[RedactionPolicy] = None):
        self._policy = policy or RedactionPolicy()
    
    def serialize(self, records: List[Dict[str, Any]], 
                  fields: List[str],
                  user_role: str = "user") -> str:
        """
        Serialize records to CSV with redaction applied.
        
        Args:
            records: List of record dictionaries
            fields: List of field names to include
            user_role: User role for redaction decisions
        
        Returns:
            CSV string with redacted fields
        """
        lines = []
        
        # Header
        lines.append(",".join(fields))
        
        # Data rows
        for record in records:
            redacted_record = self._policy.redact(record, "csv", user_role)
            row_values = []
            for field in fields:
                value = redacted_record.get(field, "")
                # Escape values containing commas or quotes
                if isinstance(value, str) and ("," in value or '"' in value):
                    escaped = value.replace('"', '""')
                    value = f'"{escaped}"'
                row_values.append(str(value))
            lines.append(",".join(row_values))
        
        return "\n".join(lines)
    
    def get_policy(self) -> RedactionPolicy:
        """Get the redaction policy."""
        return self._policy


class UIViewSerializer:
    """UI view serializer with redaction policy."""
    
    def __init__(self, policy: Optional[RedactionPolicy] = None):
        self._policy = policy or RedactionPolicy()
    
    def serialize(self, data: Dict[str, Any], user_role: str = "user") -> Dict[str, Any]:
        """
        Serialize data for UI view with redaction applied.
        
        Args:
            data: Data to serialize
            user_role: User role for redaction decisions
        
        Returns:
            Redacted data for UI
        """
        return self._policy.redact(data, "ui", user_role)
    
    def get_policy(self) -> RedactionPolicy:
        """Get the redaction policy."""
        return self._policy


# Default redaction policy for AgentOrchestration
DEFAULT_POLICY = RedactionPolicy()
DEFAULT_POLICY.add_rule("password", FieldSensitivity.RESTRICTED)
DEFAULT_POLICY.add_rule("api_key", FieldSensitivity.RESTRICTED)
DEFAULT_POLICY.add_rule("secret", FieldSensitivity.RESTRICTED)
DEFAULT_POLICY.add_rule("token", FieldSensitivity.CONFIDENTIAL, "***")
DEFAULT_POLICY.add_rule("email", FieldSensitivity.INTERNAL, "***@***.com")
DEFAULT_POLICY.add_rule("phone", FieldSensitivity.INTERNAL, "***-***-****")
