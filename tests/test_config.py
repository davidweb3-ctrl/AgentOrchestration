"""Tests for the configuration management module."""

import os
import json
import pytest
from pathlib import Path
from src.common.config import Config


class TestConfig:
    """Test suite for Config class."""

    def test_load_config(self, tmp_path):
        """Test loading configuration from a JSON file."""
        config_file = tmp_path / "config.json"
        config_file.write_text('{"app": {"name": "test", "port": 8080}}')
        config = Config(str(config_file))
        assert config.get("app.name") == "test"
        assert config.get("app.port") == 8080

    def test_load_config_file_not_found(self):
        """Test that FileNotFoundError is raised for missing config file."""
        with pytest.raises(FileNotFoundError) as exc_info:
            Config("/nonexistent/path/config.json")
        assert "Configuration file not found" in str(exc_info.value)

    def test_load_config_invalid_json(self, tmp_path):
        """Test that JSONDecodeError is raised for invalid JSON."""
        config_file = tmp_path / "config.json"
        config_file.write_text('{"invalid json')
        with pytest.raises(json.JSONDecodeError):
            Config(str(config_file))

    def test_default_value(self):
        """Test that default values are returned for missing keys."""
        config = Config()
        assert config.get("nonexistent.key", "default") == "default"
        assert config.get("nonexistent.key") is None

    def test_set_value(self):
        """Test setting config values."""
        config = Config()
        config.set("database.host", "localhost")
        assert config.get("database.host") == "localhost"

    def test_nested_set(self):
        """Test setting deeply nested config values."""
        config = Config()
        config.set("a.b.c.d", "value")
        assert config.get("a.b.c.d") == "value"

    def test_to_dict(self):
        """Test converting config to dictionary."""
        config = Config()
        config.set("key1", "value1")
        config.set("key2", "value2")
        data = config.to_dict()
        assert data["key1"] == "value1"
        assert data["key2"] == "value2"

    def test_to_dict_is_deep_copy(self):
        """Test that to_dict returns a deep copy, not a reference."""
        config = Config()
        config.set("key1", {"nested": "value"})
        data = config.to_dict()
        data["key1"]["nested"] = "modified"
        # Original config should be unchanged
        assert config.get("key1.nested") == "value"


class TestEnvOverridesAllowlist:
    """Test suite for environment variable allowlist functionality."""

    def test_env_override_allowlist_blocks_undeclared_vars(self, monkeypatch):
        """Regression test: Only documented AO_ variables should be imported.

        Issue #2017: Runtime-only values like AO_AGENT_ID should not leak
        into config snapshots. Only allowlisted keys should be imported.
        """
        # Set both allowlisted and non-allowlisted AO_ variables
        monkeypatch.setenv("AO_APP_NAME", "allowed_app")
        monkeypatch.setenv("AO_AGENT_ID", "runtime_only_value")  # Should NOT be imported
        monkeypatch.setenv("AO_UNDOCUMENTED_VAR", "should_not_appear")

        config = Config()

        # Allowlisted variable should be imported
        assert config.get("app.name") == "allowed_app"

        # Non-allowlisted variables should NOT be imported
        assert config.get("agent.id") is None
        assert config.get("undocumented.var") is None
        assert "agent" not in config.to_dict()
        assert "undocumented" not in config.to_dict()

    def test_env_override_allowlist_imports_declared_vars(self, monkeypatch):
        """Test that documented AO_ variables are properly imported."""
        monkeypatch.setenv("AO_DATABASE_HOST", "db.example.com")
        monkeypatch.setenv("AO_DATABASE_PORT", "5432")
        monkeypatch.setenv("AO_LOG_LEVEL", "debug")

        config = Config()

        assert config.get("database.host") == "db.example.com"
        assert config.get("database.port") == "5432"
        assert config.get("log.level") == "debug"

    def test_env_override_all_allowlisted_vars(self, monkeypatch):
        """Test all default allowlisted environment variables."""
        # Set all allowlisted variables
        test_values = {
            "AO_APP_NAME": "myapp",
            "AO_APP_PORT": "8080",
            "AO_APP_DEBUG": "true",
            "AO_DATABASE_HOST": "localhost",
            "AO_DATABASE_PORT": "5432",
            "AO_DATABASE_USER": "admin",
            "AO_DATABASE_PASSWORD": "secret",
            "AO_DATABASE_NAME": "mydb",
            "AO_LOG_LEVEL": "info",
            "AO_LOG_FORMAT": "json",
            "AO_LOG_OUTPUT": "stdout",
            "AO_CACHE_TTL": "3600",
            "AO_CACHE_MAX_SIZE": "1000",
            "AO_TIMEOUT_CONNECT": "30",
            "AO_TIMEOUT_READ": "60",
        }
        
        for key, value in test_values.items():
            monkeypatch.setenv(key, value)

        config = Config()

        # Verify all are imported
        assert config.get("app.name") == "myapp"
        assert config.get("app.port") == "8080"
        assert config.get("app.debug") == "true"
        assert config.get("database.host") == "localhost"
        assert config.get("database.port") == "5432"
        assert config.get("database.user") == "admin"
        assert config.get("database.password") == "secret"
        assert config.get("database.name") == "mydb"
        assert config.get("log.level") == "info"
        assert config.get("log.format") == "json"
        assert config.get("log.output") == "stdout"
        assert config.get("cache.ttl") == "3600"
        assert config.get("cache.max.size") == "1000"
        assert config.get("timeout.connect") == "30"
        assert config.get("timeout.read") == "60"


class TestEnvOverridesScopedPrefix:
    """Test suite for AO_CONFIG_ scoped prefix functionality."""

    def test_config_scoped_prefix_bypasses_allowlist(self, monkeypatch):
        """Test that AO_CONFIG_* variables bypass allowlist check."""
        monkeypatch.setenv("AO_CONFIG_CUSTOM_KEY", "custom_value")
        monkeypatch.setenv("AO_CONFIG_NESTED_DEEP_KEY", "deep_value")

        config = Config()

        # AO_CONFIG_* variables should be imported even if not in allowlist
        assert config.get("custom.key") == "custom_value"
        assert config.get("nested.deep.key") == "deep_value"

    def test_config_scoped_prefix_with_standard_prefix(self, monkeypatch):
        """Test AO_CONFIG_* works alongside standard AO_* allowlisted vars."""
        monkeypatch.setenv("AO_CONFIG_CUSTOM_VAR", "custom_value")
        monkeypatch.setenv("AO_APP_NAME", "myapp")  # In allowlist
        monkeypatch.setenv("AO_AGENT_ID", "should_not_import")  # Not in allowlist

        config = Config()

        assert config.get("custom.var") == "custom_value"
        assert config.get("app.name") == "myapp"
        assert config.get("agent.id") is None


class TestCustomAllowlist:
    """Test suite for custom allowlist functionality."""

    def test_custom_allowlist_replaces_default(self, monkeypatch):
        """Test that custom allowlist replaces the default."""
        monkeypatch.setenv("AO_APP_PORT", "9000")
        monkeypatch.setenv("AO_DATABASE_HOST", "db_host")

        # Custom allowlist only allows app.port
        config = Config(allowed_keys=["AO_APP_PORT"])

        assert config.get("app.port") == "9000"
        # Should NOT be imported even though it's in default allowlist
        assert config.get("database.host") is None

    def test_custom_allowlist_empty(self, monkeypatch):
        """Test that empty allowlist blocks all AO_ variables."""
        monkeypatch.setenv("AO_APP_NAME", "myapp")
        monkeypatch.setenv("AO_CONFIG_CUSTOM", "should_work")  # AO_CONFIG_ still works

        config = Config(allowed_keys=[])

        # AO_* variables blocked
        assert config.get("app.name") is None
        # AO_CONFIG_* still works
        assert config.get("custom") == "should_work"

    def test_is_allowlisted_method(self):
        """Test the is_allowlisted helper method."""
        config = Config()
        
        assert config.is_allowlisted("AO_APP_NAME") is True
        assert config.is_allowlisted("AO_AGENT_ID") is False
        assert config.is_allowlisted("AO_CONFIG_VAR") is False  # Not in default allowlist

    def test_is_allowlisted_with_custom_list(self):
        """Test is_allowlisted with custom allowlist."""
        config = Config(allowed_keys=["AO_CUSTOM_VAR", "AO_ANOTHER_VAR"])
        
        assert config.is_allowlisted("AO_CUSTOM_VAR") is True
        assert config.is_allowlisted("AO_ANOTHER_VAR") is True
        assert config.is_allowlisted("AO_APP_NAME") is False  # Not in custom list


class TestEnvOverrideEdgeCases:
    """Test suite for edge cases in environment variable handling."""

    def test_empty_env_var_value(self, monkeypatch):
        """Test handling of empty environment variable values."""
        monkeypatch.setenv("AO_APP_NAME", "")

        config = Config()

        # Empty string should still be imported
        assert config.get("app.name") == ""

    def test_env_var_with_special_chars(self, monkeypatch):
        """Test handling of environment variables with special characters."""
        monkeypatch.setenv("AO_CONFIG_SPECIAL", "value with spaces and symbols!@#$")

        config = Config()

        assert config.get("special") == "value with spaces and symbols!@#$"

    def test_env_var_case_sensitivity(self, monkeypatch):
        """Test that environment variable names are case sensitive."""
        monkeypatch.setenv("ao_app_name", "lowercase")  # lowercase should not match
        monkeypatch.setenv("AO_APP_NAME", "uppercase")

        config = Config()

        # Only uppercase AO_APP_NAME should be imported
        assert config.get("app.name") == "uppercase"

    def test_no_env_vars(self):
        """Test Config works when no AO_ environment variables are set."""
        # Ensure no AO_ vars are in environment
        for key in list(os.environ.keys()):
            if key.startswith("AO_"):
                del os.environ[key]

        config = Config()
        config.set("test.key", "value")

        assert config.get("test.key") == "value"


class TestConfigFileWithEnvOverrides:
    """Test suite for combining config file loading with env overrides."""

    def test_env_override_overrides_file_value(self, tmp_path, monkeypatch):
        """Test that env overrides take precedence over file values."""
        config_file = tmp_path / "config.json"
        config_file.write_text('{"app": {"name": "from_file", "port": 8080}}')
        
        monkeypatch.setenv("AO_APP_NAME", "from_env")

        config = Config(str(config_file))

        assert config.get("app.name") == "from_env"  # Env wins
        assert config.get("app.port") == 8080  # From file

    def test_config_scoped_prefix_adds_new_keys(self, tmp_path, monkeypatch):
        """Test that AO_CONFIG_* can add keys not in config file."""
        config_file = tmp_path / "config.json"
        config_file.write_text('{"app": {"name": "test"}}')
        
        monkeypatch.setenv("AO_CONFIG_NEW_SECTION_KEY", "new_value")

        config = Config(str(config_file))

        assert config.get("app.name") == "test"
        assert config.get("new.section.key") == "new_value"


# 2019-02-01T18:58:35 update

# 2019-07-31T13:45:15 update

# 2019-08-09T17:54:41 update

# 2019-08-14T16:29:54 update

# 2019-10-11T10:28:34 update

# 2019-10-25T09:23:55 update

# 2019-12-13T09:04:47 update

# 2020-04-09T10:21:21 update

# 2020-05-08T17:44:24 update

# 2020-07-20T13:54:19 update

# 2020-09-24T15:42:29 update

# 2020-12-09T20:16:24 update

# 2021-04-21T13:19:36 update

# 2021-05-25T09:15:06 update

# 2021-10-13T20:37:29 update

# 2021-11-18T18:37:15 update

# 2021-12-05T14:46:27 update

# 2022-01-19T12:56:31 update

# 2022-03-03T14:31:21 update

# 2022-03-23T08:42:05 update

# 2022-03-23T16:05:36 update

# 2022-07-11T19:00:31 update

# 2022-11-23T12:37:19 update

# 2023-01-16T15:28:31 update

# 2023-02-10T11:37:41 update

# 2023-08-01T09:43:10 update

# 2023-08-25T11:04:56 update

# 2023-09-07T10:18:27 update

# 2023-10-03T08:52:54 update

# 2023-10-11T19:49:55 update

# 2023-12-04T09:53:42 update

# 2024-01-29T14:34:37 update

# 2024-03-27T08:22:58 update

# 2024-07-03T09:52:12 update

# 2024-07-18T12:14:11 update

# 2024-09-12T10:59:12 update

# 2024-09-16T15:56:14 update

# 2024-09-17T19:00:45 update

# 2024-09-25T08:04:43 update

# 2024-12-10T14:49:57 update

# 2024-12-31T08:27:41 update

# 2025-03-18T15:08:24 update

# 2025-05-13T18:23:05 update

# 2025-05-15T19:05:40 update

# 2025-06-09T15:01:44 update

# 2025-07-04T18:13:41 update

# 2025-07-23T15:44:03 update

# 2025-10-16T13:53:26 update

# 2025-11-12T18:42:00 update

# 2026-02-06T08:55:54 update

# 2026-02-11T19:28:37 update

# 2026-04-17T10:00:53 update