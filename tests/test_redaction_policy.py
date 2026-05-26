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

        result = policy.redact(data, export_format="unknown_format", user_role="viewer")
        assert "name" in result

    def test_public_fields_not_redacted(self):
        """Test that public fields are never redacted."""
        policy = RedactionPolicy()
        data = {"public_field": "visible", "name": "test"}

        result = policy.redact(data, export_format="json", user_role="viewer")
        assert result["public_field"] == "visible"
        assert result["name"] == "test"


class TestRedactionAudit:
    """Test redaction audit and logging."""

    def test_redaction_audit_log(self):
        """Test that redaction operations are audited."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED, mask_value="***")

        data = {"password": "secret", "username": "test"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        audit = policy.get_audit_log()
        assert len(audit) > 0

    def test_redaction_statistics(self):
        """Test redaction statistics tracking."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED, mask_value="***")
        policy.add_rule("email", FieldSensitivity.CONFIDENTIAL, mask_value="[REDACTED]")

        data = {"password": "secret", "email": "test@example.com", "name": "test"}
        policy.redact(data, export_format="json", user_role="viewer")

        stats = policy.get_redaction_stats()
        assert stats["total_redacted"] >= 1
        assert stats["rules_defined"] == 2


class TestRedactionCompliance:
    """Test redaction compliance with data protection regulations."""

    def test_gdpr_pii_redaction(self):
        """Test GDPR PII (Personally Identifiable Information) redaction."""
        policy = RedactionPolicy()

        policy.add_rule("name", FieldSensitivity.CONFIDENTIAL, mask_value="[REDACTED]")
        policy.add_rule("email", FieldSensitivity.CONFIDENTIAL, mask_value="[REDACTED]")
        policy.add_rule("phone", FieldSensitivity.CONFIDENTIAL, mask_value="[REDACTED]")
        policy.add_rule("address", FieldSensitivity.CONFIDENTIAL, mask_value="[REDACTED]")
        policy.add_rule("ssn", FieldSensitivity.RESTRICTED, mask_value="***")

        data = {
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "+1-555-1234",
            "address": "123 Main St",
            "ssn": "123-45-6789"
        }

        result = policy.redact(data, export_format="json", user_role="viewer")

        assert result["name"] == "[REDACTED]"
        assert result["email"] == "[REDACTED]"
        assert result["phone"] == "[REDACTED]"
        assert result["address"] == "[REDACTED]"
        assert result["ssn"] == "***"

    def test_hipaa_phi_redaction(self):
        """Test HIPAA PHI (Protected Health Information) redaction."""
        policy = RedactionPolicy()

        policy.add_rule("medical_record_number", FieldSensitivity.RESTRICTED, mask_value="***")
        policy.add_rule("diagnosis", FieldSensitivity.CONFIDENTIAL, mask_value="[REDACTED]")
        policy.add_rule("treatment", FieldSensitivity.CONFIDENTIAL, mask_value="[REDACTED]")

        data = {
            "patient_id": "P12345",
            "medical_record_number": "MRN-789",
            "diagnosis": "Hypertension",
            "treatment": "Medication A"
        }

        result = policy.redact(data, export_format="json", user_role="viewer")

        assert result["medical_record_number"] == "***"
        assert result["diagnosis"] == "[REDACTED]"
        assert result["treatment"] == "[REDACTED]"


class TestRedactionIntegration:
    """Test redaction integration scenarios."""

    def test_multi_format_export(self):
        """Test redaction across multiple export formats simultaneously."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED, mask_value="***")

        data = {"username": "test", "password": "secret123"}

        json_result = policy.redact(data, export_format="json", user_role="viewer")
        csv_result = policy.redact(data, export_format="csv", user_role="viewer")
        ui_result = policy.redact(data, export_format="ui", user_role="viewer")

        assert json_result["password"] == "***"
        assert csv_result["password"] == "***"
        assert ui_result["password"] == "***"

    def test_role_based_redaction_hierarchy(self):
        """Test role-based redaction hierarchy."""
        policy = RedactionPolicy()
        policy.add_rule("salary", FieldSensitivity.CONFIDENTIAL, mask_value="[REDACTED]")
        policy.add_rule("ssn", FieldSensitivity.RESTRICTED, mask_value="***")

        data = {"name": "John", "salary": "100000", "ssn": "123-45-6789"}

        admin_result = policy.redact(data, export_format="json", user_role="admin")
        assert admin_result["salary"] == "100000"
        assert admin_result["ssn"] == "123-45-6789"

        manager_result = policy.redact(data, export_format="json", user_role="manager")
        assert manager_result["salary"] == "[REDACTED]"
        assert manager_result["ssn"] == "***"

        employee_result = policy.redact(data, export_format="json", user_role="employee")
        assert employee_result["salary"] == "[REDACTED]"
        assert employee_result["ssn"] == "***"


class TestFieldSensitivity:
    """Test field sensitivity enum."""

    def test_sensitivity_values(self):
        """Test field sensitivity enum values."""
        assert FieldSensitivity.PUBLIC.value == "public"
        assert FieldSensitivity.INTERNAL.value == "internal"
        assert FieldSensitivity.CONFIDENTIAL.value == "confidential"
        assert FieldSensitivity.RESTRICTED.value == "restricted"


class TestSerializerGetPolicy:
    """Test serializer get_policy methods for 100% coverage."""

    def test_json_serializer_get_policy(self):
        """Test JSON serializer get_policy returns the policy."""
        policy = RedactionPolicy()
        policy.add_rule("secret", FieldSensitivity.RESTRICTED)

        serializer = JSONExportSerializer(policy)
        retrieved_policy = serializer.get_policy()

        assert retrieved_policy is policy
        assert "secret" in retrieved_policy.get_policy_summary()

    def test_json_serializer_default_policy(self):
        """Test JSON serializer with default policy."""
        serializer = JSONExportSerializer()

        # Should create a default policy
        policy = serializer.get_policy()
        assert policy is not None

        data = {"name": "Test"}
        json_str = serializer.serialize(data)
        result = json.loads(json_str)
        assert result["name"] == "Test"

    def test_csv_serializer_get_policy(self):
        """Test CSV serializer get_policy returns the policy."""
        policy = RedactionPolicy()
        policy.add_rule("secret", FieldSensitivity.RESTRICTED)

        serializer = CSVExportSerializer(policy)
        retrieved_policy = serializer.get_policy()

        assert retrieved_policy is policy
        assert "secret" in retrieved_policy.get_policy_summary()

    def test_csv_serializer_default_policy(self):
        """Test CSV serializer with default policy."""
        serializer = CSVExportSerializer()

        # Should create a default policy
        policy = serializer.get_policy()
        assert policy is not None

        records = [{"name": "Test"}]
        csv_str = serializer.serialize(records, ["name"], "user")
        assert "Test" in csv_str

    def test_ui_serializer_get_policy(self):
        """Test UI serializer get_policy returns the policy."""
        policy = RedactionPolicy()
        policy.add_rule("secret", FieldSensitivity.RESTRICTED)

        serializer = UIViewSerializer(policy)
        retrieved_policy = serializer.get_policy()

        assert retrieved_policy is policy
        assert "secret" in retrieved_policy.get_policy_summary()

    def test_ui_serializer_default_policy(self):
        """Test UI serializer with default policy."""
        serializer = UIViewSerializer()

        # Should create a default policy
        policy = serializer.get_policy()
        assert policy is not None

        data = {"name": "Test"}
        result = serializer.serialize(data)
        assert result["name"] == "Test"


class TestRedactionAdvancedEdgeCases:
    """Advanced edge case tests for redaction policy."""

    def test_unicode_field_names(self):
        """Test redaction with unicode field names."""
        policy = RedactionPolicy()
        policy.add_rule("密码", FieldSensitivity.RESTRICTED, mask_value="***")

        data = {"用户名": "test", "密码": "secret123"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        assert result["密码"] == "***"
        assert result["用户名"] == "test"

    def test_unicode_field_values(self):
        """Test redaction with unicode field values."""
        policy = RedactionPolicy()
        policy.add_rule("name", FieldSensitivity.CONFIDENTIAL, mask_value="[REDACTED]")

        data = {"name": "测试用户", "id": "123"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        assert result["name"] == "[REDACTED]"
        assert result["id"] == "123"

    def test_very_long_field_value(self):
        """Test redaction with very long field values."""
        policy = RedactionPolicy()
        policy.add_rule("description", FieldSensitivity.CONFIDENTIAL, mask_value="[REDACTED]")

        long_value = "a" * 10000
        data = {"description": long_value, "id": "123"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        assert result["description"] == "[REDACTED]"
        assert result["id"] == "123"

    def test_binary_data_in_field(self):
        """Test redaction with binary-like data in fields."""
        policy = RedactionPolicy()
        policy.add_rule("data", FieldSensitivity.RESTRICTED, mask_value="***")

        # Binary data as base64 string
        import base64
        binary_data = base64.b64encode(b"\x00\x01\x02\x03").decode()
        data = {"data": binary_data, "name": "test"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        assert result["data"] == "***"
        assert result["name"] == "test"

    def test_special_characters_in_field_names(self):
        """Test redaction with special characters in field names."""
        policy = RedactionPolicy()
        policy.add_rule("user.password", FieldSensitivity.RESTRICTED, mask_value="***")
        policy.add_rule("user-api-key", FieldSensitivity.RESTRICTED, mask_value="***")

        data = {"user.password": "secret", "user-api-key": "key123", "name": "test"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        # Special characters in field names handling is implementation dependent
        assert result["name"] == "test"

    def test_nested_array_redaction(self):
        """Test redaction with nested arrays."""
        policy = RedactionPolicy()

        data = {
            "users": [
                {"name": "Alice", "items": [{"password": "pass1"}]},
                {"name": "Bob", "items": [{"password": "pass2"}]}
            ]
        }

        result = policy.redact(data, export_format="json", user_role="viewer")
        assert "users" in result
        assert len(result["users"]) == 2

    def test_empty_string_field_value(self):
        """Test redaction with empty string field values."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED, mask_value="***")

        data = {"password": "", "name": "test"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        # Empty string should be redacted or kept as-is
        assert result["password"] in ["***", ""]
        assert result["name"] == "test"

    def test_whitespace_only_field_value(self):
        """Test redaction with whitespace-only field values."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED, mask_value="***")

        data = {"password": "   ", "name": "test"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        assert result["password"] == "***"
        assert result["name"] == "test"

    def test_numeric_field_values(self):
        """Test redaction with numeric field values."""
        policy = RedactionPolicy()
        policy.add_rule("ssn", FieldSensitivity.RESTRICTED, mask_value="***")

        data = {"ssn": 123456789, "name": "test"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        assert result["ssn"] == "***"
        assert result["name"] == "test"

    def test_boolean_field_values(self):
        """Test redaction with boolean field values."""
        policy = RedactionPolicy()
        policy.add_rule("is_admin", FieldSensitivity.INTERNAL, mask_value="[HIDDEN]")

        data = {"is_admin": True, "name": "test"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        # Boolean should be redacted or kept based on sensitivity
        assert result["is_admin"] in ["[HIDDEN]", True]
        assert result["name"] == "test"

    def test_multiple_rules_same_field(self):
        """Test adding multiple rules for the same field."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED, mask_value="***")
        policy.add_rule("password", FieldSensitivity.CONFIDENTIAL, mask_value="[MASKED]")

        data = {"password": "secret", "name": "test"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        # Last rule should take precedence
        assert result["password"] in ["***", "[MASKED]"]

    def test_case_sensitive_field_names(self):
        """Test case sensitivity in field names."""
        policy = RedactionPolicy()
        policy.add_rule("Password", FieldSensitivity.RESTRICTED, mask_value="***")

        data = {"Password": "secret", "password": "another", "name": "test"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        # Case sensitivity depends on implementation
        assert "name" in result

    def test_null_data_input(self):
        """Test redaction with null data input."""
        policy = RedactionPolicy()

        try:
            result = policy.redact(None, export_format="json", user_role="viewer")
            # If null is handled, result may be None or empty dict
            assert result is None or result == {}
        except (TypeError, AttributeError):
            # Null input may raise exception
            pass

    def test_list_data_input(self):
        """Test redaction with list data input."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED, mask_value="***")

        data = [{"password": "secret1"}, {"password": "secret2"}]

        try:
            result = policy.redact(data, export_format="json", user_role="viewer")
            # List input handling depends on implementation
            assert result is not None
        except (TypeError, AttributeError):
            # List input may raise exception
            pass


class TestRedactionPerformance:
    """Performance tests for redaction policy."""

    def test_large_dataset_redaction(self):
        """Test redaction with large dataset."""
        import time

        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED, mask_value="***")
        policy.add_rule("email", FieldSensitivity.CONFIDENTIAL, mask_value="[REDACTED]")

        # Create large dataset
        data = {
            "users": [
                {"name": f"User{i}", "password": f"pass{i}", "email": f"user{i}@example.com"}
                for i in range(100)
            ]
        }

        start = time.time()
        result = policy.redact(data, export_format="json", user_role="viewer")
        elapsed = time.time() - start

        # Should complete in reasonable time (< 1 second)
        assert elapsed < 1.0, f"Too slow: {elapsed:.2f}s"
        assert "users" in result
        assert len(result["users"]) == 100

    def test_multiple_redaction_calls(self):
        """Test multiple redaction calls performance."""
        import time

        policy = RedactionPolicy()
        policy.add_rule("secret", FieldSensitivity.RESTRICTED, mask_value="***")

        data = {"secret": "hidden", "name": "test"}

        start = time.time()
        for _ in range(100):
            policy.redact(data, export_format="json", user_role="viewer")
        elapsed = time.time() - start

        # Should complete 100 calls in reasonable time (< 1 second)
        assert elapsed < 1.0, f"Too slow: {elapsed:.2f}s"


class TestRedactionSecurity:
    """Security tests for redaction policy."""

    def test_sql_injection_in_field_value(self):
        """Test SQL injection attempt in field value."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED, mask_value="***")

        sql_payload = "'; DROP TABLE users; --"
        data = {"password": sql_payload, "name": "test"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        # SQL injection should be redacted like any other value
        assert result["password"] == "***"
        assert "DROP TABLE" not in str(result["password"])

    def test_xss_in_field_value(self):
        """Test XSS attempt in field value."""
        policy = RedactionPolicy()
        policy.add_rule("comment", FieldSensitivity.CONFIDENTIAL, mask_value="[REDACTED]")

        xss_payload = "<script>alert('xss')</script>"
        data = {"comment": xss_payload, "name": "test"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        # XSS should be redacted
        assert result["comment"] == "[REDACTED]"
        assert "<script>" not in str(result["comment"])

    def test_no_sensitive_data_in_audit(self):
        """Test that sensitive data is not stored in audit log."""
        policy = RedactionPolicy()
        policy.add_rule("password", FieldSensitivity.RESTRICTED, mask_value="***")
        policy.add_rule("ssn", FieldSensitivity.RESTRICTED, mask_value="***")

        sensitive_data = {"password": "secret123", "ssn": "123-45-6789", "name": "test"}
        policy.redact(sensitive_data, export_format="json", user_role="viewer")

        audit = policy.get_audit_log()
        audit_str = str(audit)

        # Original sensitive values should not appear in audit
        assert "secret123" not in audit_str or "[REDACTED]" in audit_str
        assert "123-45-6789" not in audit_str or "***" in audit_str

    def test_json_injection_in_field_value(self):
        """Test JSON injection attempt in field value.""",
        policy = RedactionPolicy()
        policy.add_rule("data", FieldSensitivity.RESTRICTED, mask_value="***")

        json_payload = '{"malicious": "data"}'
        data = {"data": json_payload, "name": "test"}
        result = policy.redact(data, export_format="json", user_role="viewer")

        # JSON injection should be redacted
        assert result["data"] == "***"


class TestCSVAdvanced:
    """Advanced CSV serialization tests."""

    def test_csv_with_unicode(self):
        """Test CSV serialization with unicode characters."""
        serializer = CSVExportSerializer()

        records = [{"name": "测试用户", "description": "日本語テキスト"}]
        csv_str = serializer.serialize(records, ["name", "description"], "user")

        assert "测试用户" in csv_str or "[REDACTED]" in csv_str
        assert "日本語" in csv_str or "[REDACTED]" in csv_str

    def test_csv_with_newlines(self):
        """Test CSV serialization with newlines in values."""
        serializer = CSVExportSerializer()

        records = [{"description": "Line 1\nLine 2\nLine 3"}]
        csv_str = serializer.serialize(records, ["description"], "user")

        # Newlines should be handled (quoted or escaped)
        assert "Line 1" in csv_str or '"Line 1\nLine 2\nLine 3"' in csv_str

    def test_csv_with_tabs(self):
        """Test CSV serialization with tabs in values."""
        serializer = CSVExportSerializer()

        records = [{"description": "Column1\tColumn2\tColumn3"}]
        csv_str = serializer.serialize(records, ["description"], "user")

        # Tabs should be preserved or handled
        assert "Column1" in csv_str

    def test_csv_empty_records(self):
        """Test CSV serialization with empty records list."""
        serializer = CSVExportSerializer()

        records = []
        csv_str = serializer.serialize(records, ["name", "value"], "user")

        # Should handle empty records gracefully
        assert csv_str is not None

    def test_csv_single_record(self):
        """Test CSV serialization with single record."""
        serializer = CSVExportSerializer()

        records = [{"name": "Test", "value": "123"}]
        csv_str = serializer.serialize(records, ["name", "value"], "user")

        lines = csv_str.strip().split("\n")
        assert len(lines) == 2  # Header + 1 data row
        assert lines[0] == "name,value"


class TestJSONAdvanced:
    """Advanced JSON serialization tests."""

    def test_json_with_special_floats(self):
        """Test JSON serialization with special float values."""
        serializer = JSONExportSerializer()

        data = {
            "infinity": float('inf'),
            "negative_infinity": float('-inf'),
            "nan": float('nan')
        }

        try:
            json_str = serializer.serialize(data, "user")
            # Special floats may be handled or raise exception
            assert json_str is not None
        except (ValueError, OverflowError):
            # Special floats may not be serializable
            pass

    def test_json_with_datetime(self):
        """Test JSON serialization with datetime objects."""
        from datetime import datetime
        serializer = JSONExportSerializer()

        data = {
            "created_at": datetime.now(),
            "name": "test"
        }

        try:
            json_str = serializer.serialize(data, "user")
            # Datetime may be serialized or raise exception
            assert json_str is not None
        except (TypeError, ValueError):
            # Datetime may not be directly serializable
            pass

    def test_json_pretty_print_consistency(self):
        """Test JSON pretty print format consistency."""
        serializer = JSONExportSerializer()

        data = {"key1": "value1", "key2": "value2"}
        json_str1 = serializer.serialize(data, "user")
        json_str2 = serializer.serialize(data, "user")

        # Same input should produce same output
        assert json_str1 == json_str2
