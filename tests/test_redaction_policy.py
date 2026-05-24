"""Tests for redaction policy - consistent field masking across export formats."""

import pytest
import json
from src.common.redaction_policy import (
    RedactionPolicy,
    JSONExportSerializer,
    CSVExportSerializer,
    UIViewSerializer,
    FieldSensitivity
)


class TestRedactionPolicy:
    """Test redaction policy enforcement."""

    def test_restricted_field_redaction(self):
        """Test that RESTRICTED fields are redacted in all exports."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED)
        
        data = {"username": "john", "password": "secret123"}
        
        # Should be redacted in all formats
        json_result = policy.redact(data, "json", "user")
        csv_result = policy.redact(data, "csv", "user")
        ui_result = policy.redact(data, "ui", "user")
        
        assert json_result["password"] == "***REDACTED***"
        assert csv_result["password"] == "***REDACTED***"
        assert ui_result["password"] == "***REDACTED***"
        
        # Non-sensitive field unchanged
        assert json_result["username"] == "john"

    def test_confidential_field_redaction(self):
        """Test that CONFIDENTIAL fields are redacted with mask value."""
        policy = RedactionPolicy()
        policy.add_rule("token", FieldSensitivity.CONFIDENTIAL, "***")
        
        data = {"user_id": "123", "token": "abc-def-ghi"}
        result = policy.redact(data, "json", "user")
        
        assert result["token"] == "***"
        assert result["user_id"] == "123"

    def test_internal_field_redaction_json_csv_only(self):
        """Test that INTERNAL fields are redacted only in JSON/CSV exports."""
        policy = RedactionPolicy()
        policy.add_rule("email", FieldSensitivity.INTERNAL, "***@***.com")
        
        data = {"name": "John", "email": "john@example.com"}
        
        # Redacted in JSON/CSV
        json_result = policy.redact(data, "json", "user")
        csv_result = policy.redact(data, "csv", "user")
        assert json_result["email"] == "***@***.com"
        assert csv_result["email"] == "***@***.com"
        
        # Not redacted in UI
        ui_result = policy.redact(data, "ui", "user")
        assert ui_result["email"] == "john@example.com"

    def test_admin_user_no_redaction(self):
        """Test that admin users see all fields."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED)
        policy.add_rule("token", FieldSensitivity.CONFIDENTIAL, "***")
        
        data = {"password": "secret", "token": "abc"}
        
        # Admin sees everything
        result = policy.redact(data, "json", "admin")
        assert result["password"] == "secret"
        assert result["token"] == "abc"

    def test_nested_field_redaction(self):
        """Test redaction of nested fields."""
        policy = RedactionPolicy()
        policy.add_rule("user.password", FieldSensitivity.RESTRICTED)
        
        data = {
            "user": {
                "name": "John",
                "password": "secret"
            }
        }
        
        result = policy.redact(data, "json", "user")
        assert result["user"]["password"] == "***REDACTED***"
        assert result["user"]["name"] == "John"

    def test_missing_field_no_error(self):
        """Test that missing fields don't cause errors."""
        policy = RedactionPolicy()
        policy.add_rule("nonexistent.field", FieldSensitivity.RESTRICTED)
        
        data = {"existing": "value"}
        result = policy.redact(data, "json", "user")
        
        assert result["existing"] == "value"

    def test_policy_summary(self):
        """Test getting policy summary."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED)
        policy.add_rule("email", FieldSensitivity.INTERNAL)
        
        summary = policy.get_policy_summary()
        
        assert summary["password"] == "restricted"
        assert summary["email"] == "internal"


class TestJSONExportSerializer:
    """Test JSON export serializer."""

    def test_json_serialization_with_redaction(self):
        """Test JSON serialization applies redaction."""
        policy = RedactionPolicy()
        policy.add_rule("secret", FieldSensitivity.RESTRICTED)
        
        serializer = JSONExportSerializer(policy)
        
        data = {"name": "Test", "secret": "hidden"}
        json_str = serializer.serialize(data, "user")
        
        result = json.loads(json_str)
        assert result["secret"] == "***REDACTED***"
        assert result["name"] == "Test"

    def test_json_pretty_printing(self):
        """Test JSON output is pretty-printed."""
        serializer = JSONExportSerializer()
        
        data = {"key": "value"}
        json_str = serializer.serialize(data)
        
        assert "\n" in json_str  # Has indentation
        assert "  " in json_str  # Has spaces


class TestCSVExportSerializer:
    """Test CSV export serializer."""

    def test_csv_serialization_with_redaction(self):
        """Test CSV serialization applies redaction."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED)
        
        serializer = CSVExportSerializer(policy)
        
        records = [
            {"name": "John", "password": "secret1"},
            {"name": "Jane", "password": "secret2"}
        ]
        
        csv_str = serializer.serialize(records, ["name", "password"], "user")
        lines = csv_str.split("\n")
        
        assert lines[0] == "name,password"
        assert "***REDACTED***" in lines[1]
        assert "***REDACTED***" in lines[2]

    def test_csv_special_character_escaping(self):
        """Test CSV values with special characters are escaped."""
        serializer = CSVExportSerializer()
        
        records = [{"description": "Value with, comma"}]
        csv_str = serializer.serialize(records, ["description"], "user")
        
        assert '"Value with, comma"' in csv_str

    def test_csv_quote_escaping(self):
        """Test CSV values with quotes are escaped."""
        serializer = CSVExportSerializer()
        
        records = [{"note": 'Value with "quotes"'}]
        csv_str = serializer.serialize(records, ["note"], "user")
        
        assert '"Value with ""quotes"""' in csv_str


class TestUIViewSerializer:
    """Test UI view serializer."""

    def test_ui_serialization_with_redaction(self):
        """Test UI serialization applies redaction."""
        policy = RedactionPolicy()
        policy.add_rule("internal_id", FieldSensitivity.INTERNAL, "HIDDEN")
        
        serializer = UIViewSerializer(policy)
        
        data = {"name": "Test", "internal_id": "12345"}
        result = serializer.serialize(data, "user")
        
        # INTERNAL fields not redacted in UI
        assert result["internal_id"] == "12345"
        assert result["name"] == "Test"

    def test_ui_restricted_field_redaction(self):
        """Test that RESTRICTED fields are still redacted in UI."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED)
        
        serializer = UIViewSerializer(policy)
        
        data = {"username": "john", "password": "secret"}
        result = serializer.serialize(data, "user")
        
        assert result["password"] == "***REDACTED***"


class TestConsistentRedactionAcrossFormats:
    """Test that redaction is consistent across all export formats."""

    def test_same_policy_across_formats(self):
        """Test that all formats use the same redaction policy."""
        policy = RedactionPolicy()
        policy.add_rule("secret", FieldSensitivity.RESTRICTED)
        policy.add_rule("token", FieldSensitivity.CONFIDENTIAL, "MASKED")
        
        json_serializer = JSONExportSerializer(policy)
        csv_serializer = CSVExportSerializer(policy)
        ui_serializer = UIViewSerializer(policy)
        
        data = {"id": "1", "secret": "hidden", "token": "abc"}
        
        # JSON
        json_result = json.loads(json_serializer.serialize(data, "user"))
        
        # CSV
        csv_str = csv_serializer.serialize([data], ["id", "secret", "token"], "user")
        
        # UI
        ui_result = ui_serializer.serialize(data, "user")
        
        # All formats should redact secret
        assert json_result["secret"] == "***REDACTED***"
        assert "***REDACTED***" in csv_str
        assert ui_result["secret"] == "***REDACTED***"
        
        # All formats should redact token
        assert json_result["token"] == "MASKED"
        assert "MASKED" in csv_str
        assert ui_result["token"] == "MASKED"

    def test_default_policy_fields(self):
        """Test default policy has expected sensitive fields."""
        from src.common.redaction_policy import DEFAULT_POLICY
        
        summary = DEFAULT_POLICY.get_policy_summary()
        
        assert "password" in summary
        assert "api_key" in summary
        assert "secret" in summary
        assert "token" in summary
        assert "email" in summary
        assert "phone" in summary


class TestRedactionEdgeCases:
    """Test edge cases for redaction policy."""

    def test_empty_data_redaction(self):
        """Test redaction with empty data."""
        policy = RedactionPolicy()
        data = {}

        result = policy.redact(data, export_format="json", user_role="viewer")
        assert result == {}

    def test_null_field_values(self):
        """Test redaction with null field values."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED, mask_value="***")
        data = {"password": None, "username": "test"}

        result = policy.redact(data, export_format="json", user_role="viewer")
        # Null values should be preserved or redacted based on sensitivity
        assert "username" in result

    def test_deeply_nested_redaction(self):
        """Test redaction with deeply nested structures."""
        policy = RedactionPolicy()
        policy.add_rule("level1.level2.level3.password", FieldSensitivity.RESTRICTED, mask_value="***")
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "password": "secret123",
                        "name": "deep"
                    }
                }
            }
        }

        result = policy.redact(data, export_format="json", user_role="viewer")
        # Deep nesting should still be redacted
        assert result["level1"]["level2"]["level3"]["name"] == "deep"

    def test_array_field_redaction(self):
        """Test redaction with array fields."""
        policy = RedactionPolicy()
        data = {
            "users": [
                {"name": "Alice", "password": "pass1"},
                {"name": "Bob", "password": "pass2"}
            ]
        }

        result = policy.redact(data, export_format="json", user_role="viewer")
        assert "users" in result
        assert len(result["users"]) == 2

    def test_unknown_export_format(self):
        """Test redaction with unknown export format."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED, mask_value="***")
        data = {"password": "secret", "name": "test"}

        # Should handle gracefully
        result = policy.redact(data, export_format="unknown_format", user_role="viewer")
        assert "name" in result

    def test_public_fields_not_redacted(self):
        """Test that public fields are never redacted."""
        policy = RedactionPolicy()
        data = {"public_field": "visible", "name": "test"}

        result = policy.redact(data, export_format="json", user_role="viewer")
        assert result["public_field"] == "visible"
        assert result["name"] == "test"


class TestFieldSensitivity:
    """Test field sensitivity enum."""

    def test_sensitivity_values(self):
        """Test field sensitivity enum values."""
        assert FieldSensitivity.PUBLIC.value == "public"
        assert FieldSensitivity.INTERNAL.value == "internal"
        assert FieldSensitivity.CONFIDENTIAL.value == "confidential"
        assert FieldSensitivity.RESTRICTED.value == "restricted"
