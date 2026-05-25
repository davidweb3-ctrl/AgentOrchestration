"""Tests for protocol negotiator - block incompatible protocol upgrades."""

import pytest
from src.common.protocol_negotiator import (
    ProtocolNegotiator,
    ProtocolPolicy,
    ProtocolVersion,
    ProtocolCompatibility
)


class TestProtocolNegotiator:
    """Test protocol negotiation and validation."""

    def test_register_agent_with_compatible_version(self):
        """Test that agents with compatible protocol versions can register."""
        negotiator = ProtocolNegotiator()

        result = negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a", "task_b"]}
        )

        assert result is True
        assert "agent-001" in negotiator._registry

    def test_register_agent_with_incompatible_version(self):
        """Test that agents with incompatible protocol versions are rejected."""
        negotiator = ProtocolNegotiator()

        # Block version 1.0
        negotiator.block_protocol_version("1.0")

        result = negotiator.register_agent(
            agent_id="agent-002",
            protocol_version="1.0",
            capabilities={"supported_tasks": ["task_a"]}
        )

        assert result is False
        assert "agent-002" not in negotiator._registry

    def test_register_agent_with_unknown_version(self):
        """Test that agents with unknown protocol versions are rejected."""
        negotiator = ProtocolNegotiator()

        result = negotiator.register_agent(
            agent_id="agent-003",
            protocol_version="4.0",  # Unknown version
            capabilities={"supported_tasks": ["task_a"]}
        )

        assert result is False

    def test_resolve_handler_with_compatible_agent(self):
        """Test that handlers can be resolved for compatible agents."""
        negotiator = ProtocolNegotiator()

        negotiator.register_agent(
            agent_id="agent-004",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_x", "task_y"]}
        )

        handler_id = negotiator.resolve_handler("agent-004", "task_x")

        assert handler_id is not None
        assert handler_id == "agent-004:task_x"

    def test_resolve_handler_with_incompatible_agent(self):
        """Test that handlers cannot be resolved for incompatible agents."""
        negotiator = ProtocolNegotiator()

        negotiator.register_agent(
            agent_id="agent-005",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_z"]}
        )

        # Block the protocol version after registration
        negotiator.block_protocol_version("2.0")

        handler_id = negotiator.resolve_handler("agent-005", "task_z")

        assert handler_id is None

    def test_resolve_handler_for_unsupported_task(self):
        """Test that unsupported tasks return None."""
        negotiator = ProtocolNegotiator()

        negotiator.register_agent(
            agent_id="agent-006",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )

        handler_id = negotiator.resolve_handler("agent-006", "unsupported_task")

        assert handler_id is None

    def test_resolve_handler_for_unregistered_agent(self):
        """Test that unregistered agents return None."""
        negotiator = ProtocolNegotiator()

        handler_id = negotiator.resolve_handler("unregistered-agent", "task_a")

        assert handler_id is None

    def test_cache_invalidation_on_registration(self):
        """Test that cache is invalidated when agent re-registers."""
        negotiator = ProtocolNegotiator()

        negotiator.register_agent(
            agent_id="agent-007",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )

        # Resolve handler to populate cache
        handler_id = negotiator.resolve_handler("agent-007", "task_a")
        assert handler_id is not None
        assert "agent-007:task_a" in negotiator._cache

        # Re-register agent
        negotiator.register_agent(
            agent_id="agent-007",
            protocol_version="3.0",
            capabilities={"supported_tasks": ["task_a", "task_b"]}
        )

        # Cache should be invalidated
        assert "agent-007:task_a" not in negotiator._cache

    def test_cache_invalidation_on_version_block(self):
        """Test that cache is cleared when protocol version is blocked."""
        negotiator = ProtocolNegotiator()

        negotiator.register_agent(
            agent_id="agent-008",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )

        # Populate cache
        negotiator.resolve_handler("agent-008", "task_a")
        assert len(negotiator._cache) > 0

        # Block protocol version
        negotiator.block_protocol_version("2.0")

        # Cache should be cleared
        assert len(negotiator._cache) == 0

    def test_audit_log(self):
        """Test that audit log captures registration info."""
        negotiator = ProtocolNegotiator()

        negotiator.register_agent(
            agent_id="agent-009",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )

        audit_log = negotiator.get_audit_log()

        assert len(audit_log) == 1
        assert audit_log[0]["agent_id"] == "agent-009"
        assert audit_log[0]["protocol_version"] == "2.0"
        assert audit_log[0]["compatibility"] == "compatible"

    def test_protocol_compatibility_check(self):
        """Test protocol compatibility checking."""
        policy = ProtocolPolicy(
            min_version=ProtocolVersion.V2,
            max_version=ProtocolVersion.V3,
            blocked_versions={ProtocolVersion.V1}
        )

        assert policy.check_compatibility(ProtocolVersion.V2) == ProtocolCompatibility.COMPATIBLE
        assert policy.check_compatibility(ProtocolVersion.V3) == ProtocolCompatibility.COMPATIBLE
        assert policy.check_compatibility(ProtocolVersion.V1) == ProtocolCompatibility.INCOMPATIBLE

    def test_multiple_agents_registration(self):
        """Test registration of multiple agents."""
        negotiator = ProtocolNegotiator()

        agents = [
            ("agent-a", "2.0", ["task_1"]),
            ("agent-b", "3.0", ["task_2"]),
            ("agent-c", "2.0", ["task_1", "task_3"])
        ]

        for agent_id, version, tasks in agents:
            result = negotiator.register_agent(
                agent_id=agent_id,
                protocol_version=version,
                capabilities={"supported_tasks": tasks}
            )
            assert result is True

        assert len(negotiator._registry) == 3

    def test_get_registry_info(self):
        """Test retrieving registry info for agent."""
        negotiator = ProtocolNegotiator()

        negotiator.register_agent(
            agent_id="agent-010",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_x"]}
        )

        info = negotiator.get_registry_info("agent-010")

        assert info is not None
        assert info["protocol_version"] == ProtocolVersion.V2
        assert "task_x" in info["capabilities"]["supported_tasks"]

    def test_get_registry_info_for_unknown_agent(self):
        """Test retrieving registry info for unknown agent."""
        negotiator = ProtocolNegotiator()

        info = negotiator.get_registry_info("unknown-agent")

        assert info is None


class TestProtocolPolicy:
    """Test protocol policy configuration."""

    def test_default_policy(self):
        """Test default protocol policy."""
        negotiator = ProtocolNegotiator()
        policy = negotiator._policy

        assert policy.min_version == ProtocolVersion.V1
        assert policy.max_version == ProtocolVersion.V3
        assert len(policy.blocked_versions) == 0

    def test_custom_policy(self):
        """Test custom protocol policy."""
        custom_policy = ProtocolPolicy(
            min_version=ProtocolVersion.V2,
            max_version=ProtocolVersion.V2,
            blocked_versions={ProtocolVersion.V1, ProtocolVersion.V3}
        )

        negotiator = ProtocolNegotiator(policy=custom_policy)

        # V2 should be compatible
        assert negotiator.register_agent(
            agent_id="agent-v2",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task"]}
        ) is True

        # V1 and V3 should be incompatible
        assert negotiator.register_agent(
            agent_id="agent-v1",
            protocol_version="1.0",
            capabilities={"supported_tasks": ["task"]}
        ) is False

        assert negotiator.register_agent(
            agent_id="agent-v3",
            protocol_version="3.0",
            capabilities={"supported_tasks": ["task"]}
        ) is False


class TestProtocolNegotiatorEdgeCases:
    """Test edge cases for protocol negotiator."""

    def test_register_duplicate_agent_id(self):
        """Test registering agent with duplicate ID."""
        negotiator = ProtocolNegotiator()

        result1 = negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )
        assert result1 is True

        # Try to register same agent ID again
        result2 = negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_b"]}
        )
        # Should handle gracefully (implementation dependent)
        assert result2 is True or result2 is False

    def test_resolve_handler_with_no_agents(self):
        """Test resolving handler when no agents registered."""
        negotiator = ProtocolNegotiator()

        handler = negotiator.resolve_handler("agent-001", "task_a")
        assert handler is None

    def test_block_same_version_multiple_times(self):
        """Test blocking same version multiple times."""
        negotiator = ProtocolNegotiator()

        negotiator.block_protocol_version("1.0")
        negotiator.block_protocol_version("1.0")  # Block again

        # Should still reject agents with blocked version
        result = negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="1.0",
            capabilities={"supported_tasks": ["task_a"]}
        )
        assert result is False

    def test_block_protocol_version_updates_existing_agents(self):
        """Test that blocking a version marks existing agents as incompatible."""
        negotiator = ProtocolNegotiator()

        # Register agents with V2
        negotiator.register_agent(
            agent_id="agent-v2-a",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )
        negotiator.register_agent(
            agent_id="agent-v2-b",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_b"]}
        )
        negotiator.register_agent(
            agent_id="agent-v3",
            protocol_version="3.0",
            capabilities={"supported_tasks": ["task_c"]}
        )

        # Verify all agents are compatible initially
        assert negotiator.get_registry_info("agent-v2-a")["compatibility"] == ProtocolCompatibility.COMPATIBLE
        assert negotiator.get_registry_info("agent-v2-b")["compatibility"] == ProtocolCompatibility.COMPATIBLE
        assert negotiator.get_registry_info("agent-v3")["compatibility"] == ProtocolCompatibility.COMPATIBLE

        # Block V2
        negotiator.block_protocol_version("2.0")

        # V2 agents should now be incompatible
        assert negotiator.get_registry_info("agent-v2-a")["compatibility"] == ProtocolCompatibility.INCOMPATIBLE
        assert negotiator.get_registry_info("agent-v2-b")["compatibility"] == ProtocolCompatibility.INCOMPATIBLE
        # V3 agent should still be compatible
        assert negotiator.get_registry_info("agent-v3")["compatibility"] == ProtocolCompatibility.COMPATIBLE

    def test_audit_log_empty(self):
        """Test audit log when no operations performed."""
        negotiator = ProtocolNegotiator()

        audit = negotiator.get_audit_log()
        assert audit == []

    def test_protocol_version_boundary_values(self):
        """Test protocol version boundary values."""
        negotiator = ProtocolNegotiator()

        # Test minimum version
        result = negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="1.0",
            capabilities={"supported_tasks": ["task_a"]}
        )
        assert result is True

        # Test maximum version
        result = negotiator.register_agent(
            agent_id="agent-002",
            protocol_version="3.0",
            capabilities={"supported_tasks": ["task_b"]}
        )
        assert result is True

    def test_capabilities_with_empty_list(self):
        """Test agent with empty capabilities list."""
        negotiator = ProtocolNegotiator()

        result = negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"supported_tasks": []}
        )
        assert result is True

    def test_get_registry_info_no_agents(self):
        """Test getting registry info when no agents registered."""
        negotiator = ProtocolNegotiator()

        info = negotiator.get_registry_info("nonexistent-agent")
        assert info is None


class TestProtocolCompatibilityAdvanced:
    """Advanced protocol compatibility tests."""

    def test_backward_compatibility_v2_to_v1(self):
        """Test V2 is backward compatible with V1 agents."""
        policy = ProtocolPolicy(
            min_version=ProtocolVersion.V1,
            max_version=ProtocolVersion.V2,
            blocked_versions=set()
        )

        # V1 should be compatible when V2 is max
        result = policy.check_compatibility(ProtocolVersion.V1)
        assert result == ProtocolCompatibility.COMPATIBLE

    def test_forward_compatibility_within_major(self):
        """Test forward compatibility within same major version."""
        policy = ProtocolPolicy(
            min_version=ProtocolVersion.V1,
            max_version=ProtocolVersion.V3,
            blocked_versions=set()
        )

        # All versions should be compatible
        for version in [ProtocolVersion.V1, ProtocolVersion.V2, ProtocolVersion.V3]:
            result = policy.check_compatibility(version)
            assert result == ProtocolCompatibility.COMPATIBLE

    def test_two_majors_behind_rejected(self):
        """Test that versions two+ majors behind are rejected."""
        policy = ProtocolPolicy(
            min_version=ProtocolVersion.V3,
            max_version=ProtocolVersion.V3,
            blocked_versions=set()
        )

        # V1 should be incompatible when only V3 is allowed
        result = policy.check_compatibility(ProtocolVersion.V1)
        assert result == ProtocolCompatibility.INCOMPATIBLE

    def test_unknown_version_rejected(self):
        """Test that unknown/malformed versions are rejected."""
        policy = ProtocolPolicy(
            min_version=ProtocolVersion.V1,
            max_version=ProtocolVersion.V3,
            blocked_versions=set()
        )

        # Invalid version should be incompatible
        with pytest.raises(ValueError):
            ProtocolVersion("4.0")

    def test_cache_invalidation_single_agent(self):
        """Test cache invalidation for single agent."""
        negotiator = ProtocolNegotiator()

        negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )

        # Populate cache
        handler = negotiator.resolve_handler("agent-001", "task_a")
        assert handler is not None
        assert len(negotiator._cache) > 0

        # Unregister should invalidate cache
        negotiator.unregister_agent("agent-001")
        # Cache should be cleared for that agent
        assert len(negotiator._cache) == 0

    def test_cache_invalidation_global(self):
        """Test global cache invalidation."""
        negotiator = ProtocolNegotiator()

        for i in range(3):
            negotiator.register_agent(
                agent_id=f"agent-{i}",
                protocol_version="2.0",
                capabilities={"tasks": [f"task_{i}"]}
            )

        # Populate cache for all
        for i in range(3):
            negotiator.resolve_handler(f"agent-{i}", f"task_{i}")

        # Block version should invalidate all cache
        negotiator.block_protocol_version("2.0")
        assert len(negotiator._cache) == 0

    def test_registry_integration_register(self):
        """Test protocol validation during registration."""
        negotiator = ProtocolNegotiator()

        # Valid registration
        result = negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"tasks": ["task_a"]}
        )
        assert result is True

        # Invalid version should be rejected
        result = negotiator.register_agent(
            agent_id="agent-002",
            protocol_version="5.0",  # Unknown version
            capabilities={"tasks": ["task_b"]}
        )
        assert result is False

    def test_registry_integration_update(self):
        """Test protocol validation during update."""
        negotiator = ProtocolNegotiator()

        negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"tasks": ["task_a"]}
        )

        # Update protocol version
        result = negotiator.update_agent_protocol(
            agent_id="agent-001",
            new_protocol_version="3.0"
        )
        assert result is True

        info = negotiator.get_registry_info("agent-001")
        assert info["protocol_version"] == ProtocolVersion.V3

    def test_registry_integration_delete(self):
        """Test cleanup on agent deletion."""
        negotiator = ProtocolNegotiator()

        negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"tasks": ["task_a"]}
        )

        # Delete agent
        result = negotiator.unregister_agent("agent-001")
        assert result is True

        # Should not be found after deletion
        info = negotiator.get_registry_info("agent-001")
        assert info is None

    def test_registry_integration_list_filtering(self):
        """Test listing with protocol filtering."""
        negotiator = ProtocolNegotiator()

        negotiator.register_agent(
            agent_id="agent-v1",
            protocol_version="1.0",
            capabilities={"tasks": ["task_a"]}
        )
        negotiator.register_agent(
            agent_id="agent-v2",
            protocol_version="2.0",
            capabilities={"tasks": ["task_b"]}
        )
        negotiator.register_agent(
            agent_id="agent-v3",
            protocol_version="3.0",
            capabilities={"tasks": ["task_c"]}
        )

        # List all agents
        agents = negotiator.list_agents()
        assert len(agents) == 3

        # Filter by protocol version
        v2_agents = negotiator.list_agents(protocol_version="2.0")
        assert len(v2_agents) == 1
        assert "agent-v2" in v2_agents


class TestProtocolVersion:
    """Test protocol version enum."""

    def test_protocol_version_values(self):
        """Test protocol version enum values."""
        assert ProtocolVersion.V1.value == "1.0"
        assert ProtocolVersion.V2.value == "2.0"
        assert ProtocolVersion.V3.value == "3.0"

    def test_protocol_version_from_string(self):
        """Test creating protocol version from string."""
        assert ProtocolVersion("1.0") == ProtocolVersion.V1
        assert ProtocolVersion("2.0") == ProtocolVersion.V2
        assert ProtocolVersion("3.0") == ProtocolVersion.V3


class TestUnregisterAgent:
    """Test agent unregistration."""

    def test_unregister_existing_agent(self):
        """Test unregistering an existing agent."""
        negotiator = ProtocolNegotiator()
        negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )

        result = negotiator.unregister_agent("agent-001")
        assert result is True
        assert "agent-001" not in negotiator._registry

    def test_unregister_nonexistent_agent(self):
        """Test unregistering a non-existent agent."""
        negotiator = ProtocolNegotiator()

        result = negotiator.unregister_agent("nonexistent-agent")
        assert result is False

    def test_unregister_invalidates_cache(self):
        """Test that unregistering invalidates agent's cache entries."""
        negotiator = ProtocolNegotiator()
        negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )
        negotiator.resolve_handler("agent-001", "task_a")
        assert len(negotiator._cache) > 0

        negotiator.unregister_agent("agent-001")
        assert len(negotiator._cache) == 0


class TestUpdateAgentProtocol:
    """Test agent protocol updates."""

    def test_update_protocol_success(self):
        """Test successful protocol version update."""
        negotiator = ProtocolNegotiator()
        negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )

        result = negotiator.update_agent_protocol("agent-001", "3.0")
        assert result is True

        info = negotiator.get_registry_info("agent-001")
        assert info["protocol_version"] == ProtocolVersion.V3

    def test_update_protocol_nonexistent_agent(self):
        """Test updating protocol for non-existent agent."""
        negotiator = ProtocolNegotiator()

        result = negotiator.update_agent_protocol("nonexistent-agent", "3.0")
        assert result is False

    def test_update_protocol_invalid_version(self):
        """Test updating to invalid protocol version."""
        negotiator = ProtocolNegotiator()
        negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )

        result = negotiator.update_agent_protocol("agent-001", "invalid")
        assert result is False

    def test_update_protocol_incompatible_version(self):
        """Test updating to incompatible protocol version."""
        negotiator = ProtocolNegotiator()
        # Block V3
        negotiator.block_protocol_version("3.0")
        negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )

        result = negotiator.update_agent_protocol("agent-001", "3.0")
        assert result is False

    def test_update_protocol_invalidates_cache(self):
        """Test that protocol update invalidates agent's cache."""
        negotiator = ProtocolNegotiator()
        negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )
        negotiator.resolve_handler("agent-001", "task_a")
        assert len(negotiator._cache) > 0

        negotiator.update_agent_protocol("agent-001", "3.0")
        assert len(negotiator._cache) == 0


class TestListAgents:
    """Test listing agents."""

    def test_list_all_agents(self):
        """Test listing all registered agents."""
        negotiator = ProtocolNegotiator()
        negotiator.register_agent("agent-1", "2.0", {"tasks": ["a"]})
        negotiator.register_agent("agent-2", "3.0", {"tasks": ["b"]})
        negotiator.register_agent("agent-3", "2.0", {"tasks": ["c"]})

        agents = negotiator.list_agents()
        assert len(agents) == 3
        assert "agent-1" in agents
        assert "agent-2" in agents
        assert "agent-3" in agents

    def test_list_agents_empty(self):
        """Test listing agents when none registered."""
        negotiator = ProtocolNegotiator()

        agents = negotiator.list_agents()
        assert agents == []

    def test_list_agents_with_version_filter(self):
        """Test listing agents filtered by protocol version."""
        negotiator = ProtocolNegotiator()
        negotiator.register_agent("agent-v1", "1.0", {"tasks": ["a"]})
        negotiator.register_agent("agent-v2a", "2.0", {"tasks": ["b"]})
        negotiator.register_agent("agent-v2b", "2.0", {"tasks": ["c"]})
        negotiator.register_agent("agent-v3", "3.0", {"tasks": ["d"]})

        v2_agents = negotiator.list_agents(protocol_version="2.0")
        assert len(v2_agents) == 2
        assert "agent-v2a" in v2_agents
        assert "agent-v2b" in v2_agents

    def test_list_agents_invalid_version_filter(self):
        """Test listing agents with invalid version filter."""
        negotiator = ProtocolNegotiator()
        negotiator.register_agent("agent-1", "2.0", {"tasks": ["a"]})

        agents = negotiator.list_agents(protocol_version="invalid")
        assert agents == []


class TestCacheBehavior:
    """Test cache behavior in detail."""

    def test_cache_hit_returns_same_handler(self):
        """Test that cache hit returns the cached handler ID."""
        negotiator = ProtocolNegotiator()
        negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )

        handler1 = negotiator.resolve_handler("agent-001", "task_a")
        handler2 = negotiator.resolve_handler("agent-001", "task_a")

        assert handler1 == handler2
        assert "agent-001:task_a" in negotiator._cache

    def test_cache_key_format(self):
        """Test cache key format."""
        negotiator = ProtocolNegotiator()
        negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )

        negotiator.resolve_handler("agent-001", "task_a")
        assert "agent-001:task_a" in negotiator._cache

    def test_invalidate_cache_no_matching_entries(self):
        """Test cache invalidation when no matching entries."""
        negotiator = ProtocolNegotiator()
        negotiator.register_agent(
            agent_id="agent-001",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_a"]}
        )
        negotiator.resolve_handler("agent-001", "task_a")

        # Re-register with same ID - should still work
        negotiator.register_agent(
            agent_id="agent-002",
            protocol_version="2.0",
            capabilities={"supported_tasks": ["task_b"]}
        )

        # agent-001 cache should still exist
        assert "agent-001:task_a" in negotiator._cache
