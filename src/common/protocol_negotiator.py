"""Protocol negotiator - block incompatible protocol upgrades."""

from typing import Dict, Any, Optional, Set
from enum import Enum
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


class ProtocolVersion(Enum):
    """Supported protocol versions."""
    V1 = "1.0"
    V2 = "2.0"
    V3 = "3.0"


class ProtocolCompatibility(Enum):
    """Protocol compatibility levels."""
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    DEPRECATED = "deprecated"


@dataclass
class ProtocolPolicy:
    """Protocol policy for agent registration."""
    min_version: ProtocolVersion
    max_version: ProtocolVersion
    blocked_versions: Set[ProtocolVersion]
    
    def check_compatibility(self, version: ProtocolVersion) -> ProtocolCompatibility:
        """Check if protocol version is compatible."""
        if version in self.blocked_versions:
            return ProtocolCompatibility.INCOMPATIBLE
        
        version_order = [ProtocolVersion.V1, ProtocolVersion.V2, ProtocolVersion.V3]
        
        try:
            version_idx = version_order.index(version)
            min_idx = version_order.index(self.min_version)
            max_idx = version_order.index(self.max_version)
            
            if min_idx <= version_idx <= max_idx:
                return ProtocolCompatibility.COMPATIBLE
            else:
                return ProtocolCompatibility.INCOMPATIBLE
        except ValueError:
            return ProtocolCompatibility.INCOMPATIBLE


class ProtocolNegotiator:
    """Negotiate and validate protocol versions for agent RPC."""
    
    def __init__(self, policy: Optional[ProtocolPolicy] = None):
        self._policy = policy or self._default_policy()
        self._registry: Dict[str, Dict[str, Any]] = {}
        self._cache: Dict[str, Any] = {}
    
    def _default_policy(self) -> ProtocolPolicy:
        """Default protocol policy."""
        return ProtocolPolicy(
            min_version=ProtocolVersion.V1,
            max_version=ProtocolVersion.V3,
            blocked_versions=set()
        )
    
    def register_agent(self, agent_id: str, protocol_version: str, 
                      capabilities: Dict[str, Any]) -> bool:
        """
        Register agent with protocol version validation.
        
        Returns True if registration succeeds, False if protocol incompatible.
        """
        try:
            version = ProtocolVersion(protocol_version)
        except ValueError:
            logger.warning(f"Unknown protocol version: {protocol_version}")
            return False
        
        compatibility = self._policy.check_compatibility(version)
        
        if compatibility == ProtocolCompatibility.INCOMPATIBLE:
            logger.warning(
                f"Agent {agent_id} rejected: incompatible protocol {protocol_version}"
            )
            return False
        
        # Register agent
        self._registry[agent_id] = {
            "protocol_version": version,
            "capabilities": capabilities,
            "compatibility": compatibility
        }
        
        # Invalidate cache for this agent
        self._invalidate_cache(agent_id)
        
        logger.info(
            f"Agent {agent_id} registered with protocol {protocol_version}"
        )
        return True
    
    def resolve_handler(self, agent_id: str, task_type: str) -> Optional[str]:
        """
        Resolve handler for task, checking protocol compatibility.
        
        Returns handler ID if compatible, None otherwise.
        """
        # Check cache
        cache_key = f"{agent_id}:{task_type}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Check agent registration
        if agent_id not in self._registry:
            logger.warning(f"Agent {agent_id} not registered")
            return None
        
        agent_info = self._registry[agent_id]
        
        # Verify protocol compatibility
        if agent_info["compatibility"] != ProtocolCompatibility.COMPATIBLE:
            logger.warning(
                f"Agent {agent_id} has incompatible protocol version"
            )
            return None
        
        # Check capabilities
        capabilities = agent_info.get("capabilities", {})
        supported_tasks = capabilities.get("supported_tasks", [])
        
        if task_type not in supported_tasks:
            logger.warning(
                f"Agent {agent_id} does not support task type: {task_type}"
            )
            return None
        
        # Resolve handler
        handler_id = f"{agent_id}:{task_type}"
        self._cache[cache_key] = handler_id
        
        logger.info(f"Resolved handler {handler_id} for task {task_type}")
        return handler_id
    
    def _invalidate_cache(self, agent_id: str) -> None:
        """Invalidate cache entries for agent."""
        keys_to_remove = [
            key for key in self._cache.keys() 
            if key.startswith(f"{agent_id}:")
        ]
        for key in keys_to_remove:
            del self._cache[key]
            logger.debug(f"Invalidated cache entry: {key}")
    
    def block_protocol_version(self, version: str) -> bool:
        """Block a specific protocol version."""
        try:
            protocol_version = ProtocolVersion(version)
            self._policy.blocked_versions.add(protocol_version)
            
            # Invalidate all cache entries
            self._cache.clear()
            
            # Update existing agents with blocked version
            for agent_id, agent_info in self._registry.items():
                if agent_info["protocol_version"] == protocol_version:
                    agent_info["compatibility"] = ProtocolCompatibility.INCOMPATIBLE
                    logger.warning(f"Agent {agent_id} marked incompatible due to version block")
            
            logger.info(f"Blocked protocol version: {version}")
            return True
        except ValueError:
            logger.error(f"Invalid protocol version: {version}")
            return False
    
    def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent and cleanup resources.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            True if agent was unregistered, False if not found
        """
        if agent_id not in self._registry:
            logger.warning(f"Agent {agent_id} not found for unregistration")
            return False
        
        # Invalidate cache entries for this agent
        self._invalidate_cache(agent_id)
        
        # Remove from registry
        del self._registry[agent_id]
        
        logger.info(f"Agent {agent_id} unregistered")
        return True
    
    def update_agent_protocol(self, agent_id: str, new_protocol_version: str) -> bool:
        """Update agent's protocol version.
        
        Args:
            agent_id: Agent identifier
            new_protocol_version: New protocol version string
            
        Returns:
            True if update successful, False otherwise
        """
        if agent_id not in self._registry:
            logger.warning(f"Agent {agent_id} not found for protocol update")
            return False
        
        try:
            protocol_version = ProtocolVersion(new_protocol_version)
        except ValueError:
            logger.error(f"Invalid protocol version: {new_protocol_version}")
            return False
        
        # Check compatibility
        compatibility = self._policy.check_compatibility(protocol_version)
        if compatibility == ProtocolCompatibility.INCOMPATIBLE:
            logger.warning(
                f"Protocol version {new_protocol_version} is incompatible for agent {agent_id}"
            )
            return False
        
        # Invalidate cache
        self._invalidate_cache(agent_id)
        
        # Update agent info
        self._registry[agent_id]["protocol_version"] = protocol_version
        self._registry[agent_id]["compatibility"] = compatibility
        
        logger.info(f"Agent {agent_id} protocol updated to {new_protocol_version}")
        return True
    
    def list_agents(self, protocol_version: Optional[str] = None) -> list:
        """List all registered agents, optionally filtered by protocol version.
        
        Args:
            protocol_version: Optional protocol version filter
            
        Returns:
            List of agent IDs
        """
        if protocol_version is None:
            return list(self._registry.keys())
        
        try:
            target_version = ProtocolVersion(protocol_version)
            return [
                agent_id for agent_id, info in self._registry.items()
                if info["protocol_version"] == target_version
            ]
        except ValueError:
            logger.error(f"Invalid protocol version filter: {protocol_version}")
            return []
    
    def get_registry_info(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get registration info for agent."""
        return self._registry.get(agent_id)
    
    def get_audit_log(self) -> list:
        """Get audit log of protocol decisions."""
        # Return copy of registry for audit
        return [
            {
                "agent_id": agent_id,
                "protocol_version": info["protocol_version"].value,
                "compatibility": info["compatibility"].value,
                "capabilities": list(info["capabilities"].keys())
            }
            for agent_id, info in self._registry.items()
        ]
