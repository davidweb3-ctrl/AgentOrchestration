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
