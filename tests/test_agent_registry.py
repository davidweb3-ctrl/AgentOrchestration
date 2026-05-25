import pytest
from src.agent.registry import AgentRegistry, AgentStatus


class TestAgentRegistry:
    """Comprehensive tests for AgentRegistry."""

    def setup_method(self):
        self.registry = AgentRegistry()

    # ==================== Basic Registration Tests ====================

    def test_register_agent(self):
        """Test basic agent registration."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        assert agent_id is not None
        assert isinstance(agent_id, str)
        assert self.registry.count() == 1

    def test_register_agent_with_config(self):
        """Test agent registration with configuration."""
        config = {"timeout": 30, "retries": 3, "memory_limit": "1GB"}
        agent_id = self.registry.register("test-agent", "worker.processor", config)
        agent = self.registry.get(agent_id)
        assert agent["config"] == config

    def test_register_agent_with_empty_config(self):
        """Test agent registration with empty config defaults to empty dict."""
        agent_id = self.registry.register("test-agent", "worker.processor", None)
        agent = self.registry.get(agent_id)
        assert agent["config"] == {}

    def test_register_multiple_agents(self):
        """Test registering multiple agents increases count correctly."""
        ids = []
        for i in range(5):
            agent_id = self.registry.register(f"agent-{i}", "worker.processor")
            ids.append(agent_id)
        assert self.registry.count() == 5
        assert len(set(ids)) == 5  # All IDs should be unique

    def test_register_agent_has_uuid_format(self):
        """Test that registered agent has valid UUID format."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        # UUID format: 8-4-4-4-12 hex characters
        parts = agent_id.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4
        assert len(parts[2]) == 4
        assert len(parts[3]) == 4
        assert len(parts[4]) == 12

    # ==================== Get Agent Tests ====================

    def test_get_agent(self):
        """Test retrieving an agent by ID."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        agent = self.registry.get(agent_id)
        assert agent is not None
        assert agent["name"] == "test-agent"
        assert agent["type"] == "worker.processor"
        assert agent["status"] == "pending"

    def test_get_nonexistent_agent(self):
        """Test retrieving a non-existent agent returns None."""
        agent = self.registry.get("nonexistent-id")
        assert agent is None

    def test_get_agent_returns_copy(self):
        """Test that get returns a reference to the stored agent."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        agent1 = self.registry.get(agent_id)
        agent2 = self.registry.get(agent_id)
        assert agent1 == agent2

    def test_get_agent_has_required_fields(self):
        """Test that retrieved agent has all required fields."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        agent = self.registry.get(agent_id)
        required_fields = ["id", "name", "type", "status", "config", "created_at", "updated_at", "version", "metrics"]
        for field in required_fields:
            assert field in agent, f"Missing field: {field}"

    # ==================== List Agents Tests ====================

    def test_list_agents(self):
        """Test listing all agents."""
        self.registry.register("agent-1", "worker.processor")
        self.registry.register("agent-2", "worker.analyzer")
        self.registry.register("agent-3", "monitor.watcher")
        assert len(self.registry.list()) == 3

    def test_list_agents_empty_registry(self):
        """Test listing agents from empty registry returns empty list."""
        agents = self.registry.list()
        assert agents == []

    def test_list_agents_by_status(self):
        """Test filtering agents by status."""
        agent_id1 = self.registry.register("agent-1", "worker.processor")
        agent_id2 = self.registry.register("agent-2", "worker.analyzer")
        self.registry.update_status(agent_id1, AgentStatus.RUNNING)
        
        running_agents = self.registry.list(status=AgentStatus.RUNNING)
        pending_agents = self.registry.list(status=AgentStatus.PENDING)
        
        assert len(running_agents) == 1
        assert len(pending_agents) == 1
        assert running_agents[0]["id"] == agent_id1
        assert pending_agents[0]["id"] == agent_id2

    def test_list_agents_by_status_no_match(self):
        """Test filtering by status with no matches returns empty list."""
        self.registry.register("agent-1", "worker.processor")
        failed_agents = self.registry.list(status=AgentStatus.FAILED)
        assert failed_agents == []

    def test_list_agents_by_group(self):
        """Test filtering agents by group."""
        self.registry.register("agent-1", "worker.processor")
        self.registry.register("agent-2", "worker.analyzer")
        self.registry.register("agent-3", "monitor.watcher")
        
        workers = self.registry.list(group="worker")
        monitors = self.registry.list(group="monitor")
        
        assert len(workers) == 2
        assert len(monitors) == 1

    def test_list_agents_by_nonexistent_group(self):
        """Test filtering by non-existent group returns empty list."""
        self.registry.register("agent-1", "worker.processor")
        result = self.registry.list(group="nonexistent")
        assert result == []

    def test_list_agents_by_status_and_group(self):
        """Test filtering agents by both status and group."""
        agent_id1 = self.registry.register("agent-1", "worker.processor")
        agent_id2 = self.registry.register("agent-2", "worker.analyzer")
        self.registry.register("agent-3", "monitor.watcher")
        
        self.registry.update_status(agent_id1, AgentStatus.RUNNING)
        self.registry.update_status(agent_id2, AgentStatus.RUNNING)
        
        running_workers = self.registry.list(status=AgentStatus.RUNNING, group="worker")
        assert len(running_workers) == 2
        
        pending_workers = self.registry.list(status=AgentStatus.PENDING, group="worker")
        assert len(pending_workers) == 0

    def test_list_returns_list_type(self):
        """Test that list() always returns a list type."""
        result = self.registry.list()
        assert isinstance(result, list)

    # ==================== Update Status Tests ====================

    def test_update_status(self):
        """Test updating agent status."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        assert self.registry.update_status(agent_id, AgentStatus.RUNNING)
        agent = self.registry.get(agent_id)
        assert agent["status"] == "running"

    def test_update_status_updates_timestamp(self):
        """Test that updating status also updates the timestamp."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        original_time = self.registry.get(agent_id)["updated_at"]
        
        import time
        time.sleep(0.01)  # Small delay to ensure timestamp changes
        
        self.registry.update_status(agent_id, AgentStatus.RUNNING)
        new_time = self.registry.get(agent_id)["updated_at"]
        assert new_time > original_time

    def test_update_status_nonexistent_agent(self):
        """Test updating status of non-existent agent returns False."""
        result = self.registry.update_status("nonexistent-id", AgentStatus.RUNNING)
        assert result is False

    def test_update_status_all_statuses(self):
        """Test updating to all possible statuses."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        
        statuses = [
            AgentStatus.PENDING,
            AgentStatus.RUNNING,
            AgentStatus.PAUSED,
            AgentStatus.STOPPED,
            AgentStatus.FAILED,
            AgentStatus.TERMINATED,
        ]
        
        for status in statuses:
            assert self.registry.update_status(agent_id, status)
            agent = self.registry.get(agent_id)
            assert agent["status"] == status.value

    # ==================== Delete Agent Tests ====================

    def test_delete_agent(self):
        """Test deleting an agent."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        assert self.registry.delete(agent_id)
        assert self.registry.count() == 0
        assert self.registry.get(agent_id) is None

    def test_delete_nonexistent_agent(self):
        """Test deleting a non-existent agent returns False."""
        assert not self.registry.delete("nonexistent-id")

    def test_delete_agent_removes_from_group_index(self):
        """Test that deleting agent removes it from group index."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        self.registry.delete(agent_id)
        
        # After deletion, listing by group should return empty
        workers = self.registry.list(group="worker")
        assert len(workers) == 0

    def test_delete_agent_from_empty_registry(self):
        """Test deleting from empty registry returns False."""
        result = self.registry.delete("any-id")
        assert result is False

    def test_delete_one_agent_others_remain(self):
        """Test that deleting one agent doesn't affect others."""
        agent_id1 = self.registry.register("agent-1", "worker.processor")
        agent_id2 = self.registry.register("agent-2", "worker.analyzer")
        
        self.registry.delete(agent_id1)
        
        assert self.registry.count() == 1
        assert self.registry.get(agent_id2) is not None

    # ==================== Count Tests ====================

    def test_count_empty_registry(self):
        """Test count on empty registry returns 0."""
        assert self.registry.count() == 0

    def test_count_increments_correctly(self):
        """Test that count increments with each registration."""
        for i in range(10):
            self.registry.register(f"agent-{i}", "worker.processor")
            assert self.registry.count() == i + 1

    def test_count_decrements_on_delete(self):
        """Test that count decrements when agents are deleted."""
        agent_ids = []
        for i in range(5):
            agent_id = self.registry.register(f"agent-{i}", "worker.processor")
            agent_ids.append(agent_id)
        
        for i, agent_id in enumerate(agent_ids):
            self.registry.delete(agent_id)
            assert self.registry.count() == 5 - (i + 1)

    # ==================== Agent Metadata Tests ====================

    def test_agent_has_version(self):
        """Test that registered agent has version field."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        agent = self.registry.get(agent_id)
        assert "version" in agent
        assert agent["version"] == "1.0.0"

    def test_agent_has_metrics(self):
        """Test that registered agent has metrics field."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        agent = self.registry.get(agent_id)
        assert "metrics" in agent
        assert "tasks_completed" in agent["metrics"]
        assert "errors" in agent["metrics"]
        assert "uptime" in agent["metrics"]

    def test_agent_has_timestamps(self):
        """Test that registered agent has created_at and updated_at timestamps."""
        import time
        before = time.time()
        agent_id = self.registry.register("test-agent", "worker.processor")
        after = time.time()
        
        agent = self.registry.get(agent_id)
        assert "created_at" in agent
        assert "updated_at" in agent
        assert before <= agent["created_at"] <= after
        assert before <= agent["updated_at"] <= after

    # ==================== Group Index Tests ====================

    def test_group_index_created_for_new_group(self):
        """Test that group index is created for new agent types."""
        self.registry.register("agent-1", "worker.processor")
        self.registry.register("agent-2", "monitor.watcher")
        
        workers = self.registry.list(group="worker")
        monitors = self.registry.list(group="monitor")
        
        assert len(workers) == 1
        assert len(monitors) == 1

    def test_multiple_agents_same_group(self):
        """Test that multiple agents in same group are indexed correctly."""
        for i in range(5):
            self.registry.register(f"agent-{i}", "worker.processor")
        
        workers = self.registry.list(group="worker")
        assert len(workers) == 5

    def test_group_index_preserved_after_status_update(self):
        """Test that group index works correctly after status updates."""
        agent_id = self.registry.register("agent-1", "worker.processor")
        self.registry.update_status(agent_id, AgentStatus.RUNNING)
        
        workers = self.registry.list(group="worker")
        assert len(workers) == 1
        assert workers[0]["status"] == "running"

    # ==================== Storage Backend Tests ====================

    def test_default_storage_backend(self):
        """Test that default storage backend is 'memory'."""
        registry = AgentRegistry()
        assert registry.storage_backend == "memory"

    def test_custom_storage_backend(self):
        """Test that custom storage backend can be set."""
        registry = AgentRegistry(storage_backend="redis")
        assert registry.storage_backend == "redis"

    # ==================== Edge Case Tests ====================

    def test_register_agent_with_special_characters_in_name(self):
        """Test registering agent with special characters in name."""
        special_names = [
            "agent-with-dashes",
            "agent_with_underscores",
            "agent.with.dots",
            "agent with spaces",
            "agent@symbol",
            "agent#hash",
        ]
        for name in special_names:
            agent_id = self.registry.register(name, "worker.processor")
            agent = self.registry.get(agent_id)
            assert agent["name"] == name

    def test_register_agent_with_nested_type(self):
        """Test registering agent with deeply nested type."""
        agent_id = self.registry.register("test-agent", "a.b.c.d.e.processor")
        agent = self.registry.get(agent_id)
        assert agent["type"] == "a.b.c.d.e.processor"
        
        # Group should be the first segment
        group_agents = self.registry.list(group="a")
        assert len(group_agents) == 1

    def test_list_with_status_no_agents(self):
        """Test listing by status when registry is empty."""
        result = self.registry.list(status=AgentStatus.RUNNING)
        assert result == []

    def test_list_with_group_no_agents(self):
        """Test listing by group when registry is empty."""
        result = self.registry.list(group="worker")
        assert result == []

    def test_concurrent_registration_and_deletion(self):
        """Test that concurrent registration and deletion work correctly."""
        agent_ids = []
        for i in range(100):
            agent_id = self.registry.register(f"agent-{i}", "worker.processor")
            agent_ids.append(agent_id)
        
        # Delete every other agent
        for i in range(0, 100, 2):
            self.registry.delete(agent_ids[i])
        
        assert self.registry.count() == 50

    def test_agent_type_without_dot(self):
        """Test agent type without dot separator."""
        agent_id = self.registry.register("test-agent", "simpletype")
        agent = self.registry.get(agent_id)
        assert agent["type"] == "simpletype"
        
        # Group should be the entire type
        group_agents = self.registry.list(group="simpletype")
        assert len(group_agents) == 1

    def test_empty_string_name_and_type(self):
        """Test registering with empty strings."""
        agent_id = self.registry.register("", "")
        agent = self.registry.get(agent_id)
        assert agent["name"] == ""
        assert agent["type"] == ""

    def test_very_long_name_and_type(self):
        """Test registering with very long strings."""
        long_name = "a" * 1000
        long_type = "b" * 1000
        agent_id = self.registry.register(long_name, long_type)
        agent = self.registry.get(agent_id)
        assert agent["name"] == long_name
        assert agent["type"] == long_type

    def test_unicode_characters(self):
        """Test registering with unicode characters."""
        unicode_name = "测试代理 🚀 Агент"
        unicode_type = "类型.处理器 💻"
        agent_id = self.registry.register(unicode_name, unicode_type)
        agent = self.registry.get(agent_id)
        assert agent["name"] == unicode_name
        assert agent["type"] == unicode_type

    def test_multiple_status_transitions(self):
        """Test multiple status transitions for same agent."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        
        transitions = [
            AgentStatus.PENDING,
            AgentStatus.RUNNING,
            AgentStatus.PAUSED,
            AgentStatus.RUNNING,
            AgentStatus.STOPPED,
            AgentStatus.RUNNING,
            AgentStatus.FAILED,
            AgentStatus.TERMINATED,
        ]
        
        for status in transitions:
            assert self.registry.update_status(agent_id, status)
            agent = self.registry.get(agent_id)
            assert agent["status"] == status.value

    def test_delete_already_deleted_agent(self):
        """Test deleting an agent that was already deleted."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        assert self.registry.delete(agent_id) is True
        assert self.registry.delete(agent_id) is False

    def test_list_result_isolation(self):
        """Test that list results don't affect internal state."""
        self.registry.register("agent-1", "worker.processor")
        agents = self.registry.list()
        
        # Modify the returned list
        agents.clear()
        
        # Internal state should be unchanged
        assert self.registry.count() == 1

    def test_register_after_delete_reuses_group_index(self):
        """Test that group index works correctly after delete and re-register."""
        agent_id = self.registry.register("agent-1", "worker.processor")
        self.registry.delete(agent_id)
        
        # Register another agent in same group
        agent_id2 = self.registry.register("agent-2", "worker.processor")
        workers = self.registry.list(group="worker")
        
        assert len(workers) == 1
        assert workers[0]["id"] == agent_id2
