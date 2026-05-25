"""Tests for plugin registry - duplicate capability name detection."""

import pytest
from src.common.plugin_registry import PluginRegistry, PluginCapability


class TestPluginRegistry:
    """Test plugin registration with duplicate detection."""

    def test_register_plugin_with_unique_capabilities(self):
        """Test that plugins with unique capabilities can register."""
        registry = PluginRegistry()
        
        result = registry.register_plugin(
            "plugin-1",
            [{"name": "capability-a", "version": "1.0"}]
        )
        
        assert result is True
        assert "capability-a" in registry.get_registered_capabilities()

    def test_register_plugin_with_duplicate_capability(self):
        """Test that plugins with duplicate capabilities are rejected."""
        registry = PluginRegistry()
        
        # Register first plugin
        registry.register_plugin(
            "plugin-1",
            [{"name": "capability-a", "version": "1.0"}]
        )
        
        # Try to register second plugin with same capability
        result = registry.register_plugin(
            "plugin-2",
            [{"name": "capability-a", "version": "2.0"}]
        )
        
        assert result is False

    def test_register_plugin_with_multiple_capabilities(self):
        """Test registering plugin with multiple capabilities."""
        registry = PluginRegistry()
        
        result = registry.register_plugin(
            "plugin-1",
            [
                {"name": "cap-a", "version": "1.0"},
                {"name": "cap-b", "version": "1.0"}
            ]
        )
        
        assert result is True
        capabilities = registry.get_registered_capabilities()
        assert "cap-a" in capabilities
        assert "cap-b" in capabilities

    def test_capability_without_name_rejected(self):
        """Test that capabilities without names are rejected."""
        registry = PluginRegistry()
        
        result = registry.register_plugin(
            "plugin-1",
            [{"version": "1.0"}]  # No name
        )
        
        assert result is False

    def test_resolve_capability(self):
        """Test resolving a capability to its plugin."""
        registry = PluginRegistry()
        
        registry.register_plugin(
            "plugin-1",
            [{"name": "capability-a", "version": "1.0"}]
        )
        
        handler = registry.resolve_capability("capability-a")
        
        assert handler == "plugin-1"

    def test_resolve_nonexistent_capability(self):
        """Test resolving a non-existent capability returns None."""
        registry = PluginRegistry()
        
        handler = registry.resolve_capability("nonexistent")
        
        assert handler is None

    def test_unregister_plugin(self):
        """Test unregistering a plugin removes its capabilities."""
        registry = PluginRegistry()
        
        registry.register_plugin(
            "plugin-1",
            [{"name": "capability-a", "version": "1.0"}]
        )
        
        result = registry.unregister_plugin("plugin-1")
        
        assert result is True
        assert "capability-a" not in registry.get_registered_capabilities()

    def test_unregister_nonexistent_plugin(self):
        """Test unregistering a non-existent plugin returns False."""
        registry = PluginRegistry()
        
        result = registry.unregister_plugin("nonexistent")
        
        assert result is False

    def test_cache_invalidation_on_registration(self):
        """Test that cache is invalidated when new plugin registers."""
        registry = PluginRegistry()
        
        registry.register_plugin(
            "plugin-1",
            [{"name": "capability-a", "version": "1.0"}]
        )
        
        # Resolve to populate cache
        registry.resolve_capability("capability-a")
        assert len(registry._cache) > 0
        
        # Register new plugin
        registry.register_plugin(
            "plugin-2",
            [{"name": "capability-b", "version": "1.0"}]
        )
        
        # Cache should be cleared
        assert len(registry._cache) == 0

    def test_resolve_uses_cache(self):
        """Test that resolve_capability uses cached value on second call."""
        registry = PluginRegistry()
        
        registry.register_plugin(
            "plugin-1",
            [{"name": "capability-a", "version": "1.0"}]
        )
        
        # First resolve - should populate cache
        handler1 = registry.resolve_capability("capability-a")
        assert handler1 == "plugin-1"
        assert len(registry._cache) == 1
        
        # Second resolve - should use cache
        handler2 = registry.resolve_capability("capability-a")
        assert handler2 == "plugin-1"

    def test_cache_invalidation_on_unregistration(self):
        """Test that cache is invalidated when plugin unregisters."""
        registry = PluginRegistry()
        
        registry.register_plugin(
            "plugin-1",
            [{"name": "capability-a", "version": "1.0"}]
        )
        
        # Resolve to populate cache
        registry.resolve_capability("capability-a")
        assert len(registry._cache) > 0
        
        # Unregister plugin
        registry.unregister_plugin("plugin-1")
        
        # Cache should be cleared
        assert len(registry._cache) == 0

    def test_get_plugin_info(self):
        """Test getting plugin information."""
        registry = PluginRegistry()
        
        registry.register_plugin(
            "plugin-1",
            [{"name": "capability-a", "version": "1.0"}]
        )
        
        info = registry.get_plugin_info("plugin-1")
        
        assert info is not None
        assert len(info["capabilities"]) == 1

    def test_get_audit_log(self):
        """Test getting audit log of registrations."""
        registry = PluginRegistry()
        
        registry.register_plugin(
            "plugin-1",
            [
                {"name": "cap-a", "version": "1.0"},
                {"name": "cap-b", "version": "1.0"}
            ]
        )
        
        audit = registry.get_audit_log()
        
        assert len(audit) == 1
        assert audit[0]["plugin_id"] == "plugin-1"
        assert audit[0]["capability_count"] == 2

    def test_duplicate_detection_across_multiple_plugins(self):
        """Test duplicate detection works across multiple plugins."""
        registry = PluginRegistry()
        
        # Register first plugin
        registry.register_plugin(
            "plugin-1",
            [{"name": "cap-a", "version": "1.0"}]
        )
        
        # Register second plugin with different capability
        registry.register_plugin(
            "plugin-2",
            [{"name": "cap-b", "version": "1.0"}]
        )
        
        # Try to register third plugin with duplicate
        result = registry.register_plugin(
            "plugin-3",
            [{"name": "cap-a", "version": "2.0"}]  # Duplicate of plugin-1
        )
        
        assert result is False


class TestPluginRegistryEdgeCases:
    """Test edge cases for plugin registry."""

    def test_resolve_capability_logs_warning_when_not_found(self, caplog):
        """Test that resolving non-existent capability logs warning."""
        import logging
        registry = PluginRegistry()
        
        with caplog.at_level(logging.WARNING):
            # This should trigger the warning log on line 77
            handler = registry.resolve_capability("nonexistent-capability")
            assert handler is None
        
        # Verify warning was logged
        assert "not found" in caplog.text or "nonexistent-capability" in caplog.text

    def test_register_plugin_with_empty_capabilities(self):
        """Test registering plugin with empty capabilities list."""
        registry = PluginRegistry()
        
        result = registry.register_plugin("plugin-1", [])
        # Should succeed but with no capabilities
        assert result is True
        assert len(registry.get_registered_capabilities()) == 0

    def test_get_plugin_info_nonexistent(self):
        """Test getting info for non-existent plugin."""
        registry = PluginRegistry()
        
        info = registry.get_plugin_info("nonexistent")
        assert info is None

    def test_audit_log_empty(self):
        """Test audit log when no plugins registered."""
        registry = PluginRegistry()
        
        audit = registry.get_audit_log()
        assert audit == []

    def test_multiple_capabilities_same_plugin(self):
        """Test plugin with many capabilities."""
        registry = PluginRegistry()
        
        capabilities = [
            {"name": f"cap-{i}", "version": "1.0"}
            for i in range(10)
        ]
        
        result = registry.register_plugin("plugin-1", capabilities)
        assert result is True
        assert len(registry.get_registered_capabilities()) == 10


class TestPluginRegistryAdvanced:
    """Advanced plugin registry tests."""

    def test_plugin_version_upgrade(self):
        """Test plugin version upgrade scenario."""
        registry = PluginRegistry()

        # Register initial version
        registry.register_plugin(
            "plugin-1",
            [{"name": "cap-a", "version": "1.0"}]
        )

        # Unregister old version
        registry.unregister_plugin("plugin-1")

        # Register new version with same capability
        result = registry.register_plugin(
            "plugin-1-v2",
            [{"name": "cap-a", "version": "2.0"}]
        )

        assert result is True

    def test_capability_conflict_resolution(self):
        """Test capability conflict resolution."""
        registry = PluginRegistry()

        # First plugin registers capability
        registry.register_plugin(
            "plugin-1",
            [{"name": "shared-cap", "version": "1.0"}]
        )

        # Second plugin tries to register same capability
        result = registry.register_plugin(
            "plugin-2",
            [{"name": "shared-cap", "version": "2.0"}]
        )

        # Should be rejected due to duplicate
        assert result is False

        # First plugin unregisters
        registry.unregister_plugin("plugin-1")

        # Now second plugin can register
        result = registry.register_plugin(
            "plugin-2",
            [{"name": "shared-cap", "version": "2.0"}]
        )
        assert result is True

    def test_bulk_plugin_operations(self):
        """Test bulk plugin operations."""
        registry = PluginRegistry()

        # Bulk register
        for i in range(10):
            registry.register_plugin(
                f"plugin-{i}",
                [{"name": f"cap-{i}", "version": "1.0"}]
            )

        assert len(registry.get_registered_capabilities()) == 10

        # Bulk unregister
        for i in range(10):
            registry.unregister_plugin(f"plugin-{i}")

        assert len(registry.get_registered_capabilities()) == 0


class TestPluginRegistryPerformance:
    """Plugin registry performance tests."""

    def test_large_scale_registration(self):
        """Test registration with large number of plugins."""
        registry = PluginRegistry()

        # Register 50 plugins with 2 capabilities each
        for i in range(50):
            registry.register_plugin(
                f"plugin-{i}",
                [
                    {"name": f"cap-{i}-a", "version": "1.0"},
                    {"name": f"cap-{i}-b", "version": "1.0"}
                ]
            )

        assert len(registry.get_registered_capabilities()) == 100

    def test_capability_lookup_performance(self):
        """Test capability lookup with many registered capabilities."""
        registry = PluginRegistry()

        # Register many capabilities
        for i in range(100):
            registry.register_plugin(
                f"plugin-{i}",
                [{"name": f"cap-{i}", "version": "1.0"}]
            )

        # Lookup should be fast (cached)
        handler = registry.resolve_capability("cap-50")
        assert handler == "plugin-50"


class TestPluginRegistryIntegration:
    """Plugin registry integration tests."""

    def test_end_to_end_plugin_lifecycle(self):
        """Test complete plugin lifecycle."""
        registry = PluginRegistry()

        # 1. Register plugin
        result = registry.register_plugin(
            "my-plugin",
            [
                {"name": "feature-a", "version": "1.0"},
                {"name": "feature-b", "version": "1.0"}
            ]
        )
        assert result is True

        # 2. Resolve capabilities
        handler_a = registry.resolve_capability("feature-a")
        handler_b = registry.resolve_capability("feature-b")
        assert handler_a == "my-plugin"
        assert handler_b == "my-plugin"

        # 3. Get plugin info
        info = registry.get_plugin_info("my-plugin")
        assert info is not None
        assert len(info["capabilities"]) == 2

        # 4. Unregister plugin
        result = registry.unregister_plugin("my-plugin")
        assert result is True

        # 5. Verify cleanup
        assert registry.resolve_capability("feature-a") is None
        assert registry.get_plugin_info("my-plugin") is None


class TestPluginCapability:
    """Test PluginCapability dataclass."""

    def test_capability_creation(self):
        """Test creating a PluginCapability."""
        cap = PluginCapability(
            name="test-cap",
            version="1.0",
            handler="plugin-1"
        )

        assert cap.name == "test-cap"
        assert cap.version == "1.0"
        assert cap.handler == "plugin-1"
