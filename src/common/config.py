"""Configuration management module.

This module provides a Config class for loading and managing application
configuration from JSON files with environment variable overrides.

Environment Variable Overrides:
    AO_<VAR_NAME>: Override config values for keys in the allowlist
    AO_CONFIG_<VAR_NAME>: Always override config values (bypasses allowlist)
    
    Examples:
        AO_APP_NAME=myapp -> sets config['app']['name'] = 'myapp'
        AO_DATABASE_HOST=localhost -> sets config['database']['host'] = 'localhost'
        AO_CONFIG_CUSTOM_KEY=value -> sets config['custom']['key'] = 'value'
"""

import os
import json
from typing import Any, Dict, List, Optional, Set


class Config:
    """Configuration manager with file loading and environment overrides.
    
    Supports loading configuration from JSON files and overriding values
    via environment variables. Only allowlisted AO_ variables are imported
    to prevent runtime-only values (like AO_AGENT_ID) from leaking into
    config snapshots.
    
    Attributes:
        CONFIG_OVERRIDES_ALLOWLIST: Set of AO_ prefixed env var names that
            are allowed to override config values.
        CONFIG_SCOPED_PREFIX: Prefix for env vars that always override config
            regardless of allowlist.
    """
    
    # Allowlist of documented config override keys
    # Only these AO_ prefixed variables will be imported into config
    # when using the standard AO_ prefix (not AO_CONFIG_)
    CONFIG_OVERRIDES_ALLOWLIST: Set[str] = {
        "AO_APP_NAME",
        "AO_APP_PORT",
        "AO_APP_DEBUG",
        "AO_DATABASE_HOST",
        "AO_DATABASE_PORT",
        "AO_DATABASE_USER",
        "AO_DATABASE_PASSWORD",
        "AO_DATABASE_NAME",
        "AO_LOG_LEVEL",
        "AO_LOG_FORMAT",
        "AO_LOG_OUTPUT",
        "AO_CACHE_TTL",
        "AO_CACHE_MAX_SIZE",
        "AO_TIMEOUT_CONNECT",
        "AO_TIMEOUT_READ",
    }
    
    # Scoped prefix that bypasses allowlist check
    # AO_CONFIG_* variables are always imported as config overrides
    CONFIG_SCOPED_PREFIX: str = "AO_CONFIG_"

    def __init__(
        self,
        config_path: Optional[str] = None,
        allowed_keys: Optional[List[str]] = None
    ):
        """Initialize Config instance.
        
        Args:
            config_path: Optional path to JSON config file to load.
            allowed_keys: Optional custom allowlist of AO_ variable names.
                         If provided, replaces the default allowlist.
        """
        self._data: Dict[str, Any] = {}
        self._allowed_keys: Set[str] = (
            set(allowed_keys) if allowed_keys is not None 
            else set(self.CONFIG_OVERRIDES_ALLOWLIST)
        )
        
        if config_path:
            self.load(config_path)
        
        self._load_env_overrides()

    def load(self, path: str) -> None:
        """Load configuration from a JSON file.
        
        Args:
            path: Path to the JSON configuration file.
            
        Raises:
            FileNotFoundError: If the config file does not exist.
            json.JSONDecodeError: If the file contains invalid JSON.
            PermissionError: If the file cannot be read.
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self._data = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file not found: {path}")
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                f"Invalid JSON in config file {path}: {e.msg}",
                e.doc,
                e.pos
            )

    def _load_env_overrides(self) -> None:
        """Load environment variable overrides into config.
        
        Processes environment variables in two categories:
        1. AO_CONFIG_*: Always imported (bypasses allowlist)
        2. AO_*: Only imported if in allowlist
        
        Variable names are converted to nested config keys:
        AO_APP_NAME -> config['app']['name']
        AO_CONFIG_DB_HOST -> config['db']['host']
        """
        for key, value in os.environ.items():
            if key.startswith(self.CONFIG_SCOPED_PREFIX):
                # AO_CONFIG_* variables always override (bypass allowlist)
                suffix = key[len(self.CONFIG_SCOPED_PREFIX):]
                config_key = suffix.lower().replace("_", ".")
                self._set_nested(config_key, value)
            elif key.startswith("AO_"):
                # AO_* variables only override if in allowlist
                if key in self._allowed_keys:
                    config_key = key[3:].lower().replace("_", ".")
                    self._set_nested(config_key, value)

    def _set_nested(self, key: str, value: Any) -> None:
        """Set a nested config value using dot notation.
        
        Args:
            key: Dot-separated key path (e.g., 'database.host')
            value: Value to set at the specified path
        """
        parts = key.split(".")
        current = self._data
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value using dot notation.
        
        Args:
            key: Dot-separated key path (e.g., 'app.name')
            default: Default value if key is not found
            
        Returns:
            The config value or default if not found.
        """
        parts = key.split(".")
        current = self._data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
                if current is None:
                    return default
            else:
                return default
        return current

    def set(self, key: str, value: Any) -> None:
        """Set a config value using dot notation.
        
        Args:
            key: Dot-separated key path (e.g., 'database.host')
            value: Value to set
        """
        self._set_nested(key, value)

    def to_dict(self) -> Dict[str, Any]:
        """Return a copy of the configuration as a dictionary.
        
        Returns:
            Deep copy of the current configuration.
        """
        return json.loads(json.dumps(self._data))

    def is_allowlisted(self, env_var_name: str) -> bool:
        """Check if an environment variable name is in the allowlist.
        
        Args:
            env_var_name: The environment variable name to check.
            
        Returns:
            True if the variable is allowlisted, False otherwise.
        """
        return env_var_name in self._allowed_keys


# 2019-03-14T15:29:32 update

# 2019-05-06T15:01:41 update

# 2019-07-12T09:57:32 update

# 2019-08-30T16:15:51 update

# 2019-08-30T19:29:48 update

# 2019-11-29T18:40:08 update

# 2020-01-06T17:10:44 update

# 2020-01-23T10:35:15 update

# 2020-04-27T16:39:24 update

# 2020-05-26T16:41:05 update

# 2020-07-19T11:00:28 update

# 2021-02-26T14:06:47 update

# 2021-04-25T15:41:25 update

# 2021-05-03T10:13:52 update

# 2021-05-25T19:02:26 update

# 2021-07-20T13:34:30 update

# 2021-09-23T13:29:24 update

# 2021-11-12T13:25:31 update

# 2022-01-07T11:55:24 update

# 2022-03-08T17:13:29 update

# 2022-03-09T12:33:27 update

# 2022-03-24T14:25:02 update

# 2022-04-12T20:49:22 update

# 2022-04-13T15:58:33 update

# 2022-06-03T19:19:58 update

# 2022-09-27T19:11:22 update

# 2022-11-16T19:38:41 update

# 2022-12-19T10:51:08 update

# 2022-12-24T10:03:34 update

# 2023-01-05T20:57:10 update

# 2023-02-02T10:54:16 update

# 2023-02-07T11:41:49 update

# 2023-02-24T17:40:44 update

# 2023-03-31T13:02:20 update

# 2023-05-29T19:56:24 update

# 2023-09-16T09:50:57 update

# 2023-11-22T08:33:39 update

# 2023-12-28T20:23:43 update

# 2024-02-19T11:33:12 update

# 2024-05-09T14:00:07 update

# 2024-06-28T11:57:44 update

# 2024-09-05T13:13:46 update

# 2024-09-06T09:08:29 update

# 2024-09-08T20:18:45 update

# 2024-10-09T08:26:36 update

# 2024-11-28T15:26:38 update

# 2024-12-04T19:45:11 update

# 2025-03-07T15:33:54 update

# 2025-07-11T11:44:03 update

# 2025-08-06T12:39:27 update

# 2025-09-17T08:36:34 update

# 2025-10-08T10:41:39 update

# 2025-10-20T15:13:02 update

# 2026-01-12T19:44:27 update

# 2026-02-06T14:54:33 update

# 2026-04-10T20:09:37 update