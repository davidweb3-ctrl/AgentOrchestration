"""Plugin registry with duplicate capability name detection."""

from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class PluginCapability:
    """Plugin capability definition."""
    name: str
    version: str
    handler: str


class PluginRegistry:
    """Registry for plugins with duplicate capability detection."""
    
    def __init__(self):
        self._plugins: Dict[str, Dict[str, Any]] = {}
        self._capabilities: Dict[str, PluginCapability] = {}
        self._cache: Dict[str, Any] = {}
    
    def register_plugin(self, plugin_id: str, capabilities: List[Dict[str, str]]) -> bool:
        """
        Register a plugin with its capabilities.
        
        Returns True if registration succeeds, False if duplicate capability detected.
        """
        # Check for duplicate capability names
        for cap in capabilities:
            cap_name = cap.get('name')
            if not cap_name:
                logger.warning(f"Plugin {plugin_id} has capability without name")
                return False
            
            if cap_name in self._capabilities:
                existing = self._capabilities[cap_name]
                logger.warning(
                    f"Duplicate capability '{cap_name}' detected. "
                    f"Already registered by plugin {existing.handler}"
                )
                return False
        
        # Register plugin
        import time
        self._plugins[plugin_id] = {
            'capabilities': capabilities,
            'registered_at': time.time()
        }
        
        # Register capabilities
        for cap in capabilities:
            cap_name = cap.get('name')
            self._capabilities[cap_name] = PluginCapability(
                name=cap_name,
                version=cap.get('version', '1.0'),
                handler=plugin_id
            )
        
        # Invalidate cache
        self._invalidate_cache()
        
        logger.info(f"Plugin {plugin_id} registered with {len(capabilities)} capabilities")
        return True
    
    def resolve_capability(self, capability_name: str) -> Optional[str]:
        """
        Resolve a capability to its handler plugin.
        
        Returns plugin_id if found, None otherwise.
        """
        # Check cache
        if capability_name in self._cache:
            return self._cache[capability_name]
        
        # Look up capability
        if capability_name not in self._capabilities:
            logger.warning(f"Capability '{capability_name}' not found")
            return None
        
        cap = self._capabilities[capability_name]
        self._cache[capability_name] = cap.handler
        
        logger.info(f"Resolved capability '{capability_name}' to plugin {cap.handler}")
        return cap.handler
    
    def unregister_plugin(self, plugin_id: str) -> bool:
        """Unregister a plugin and its capabilities."""
        if plugin_id not in self._plugins:
            logger.warning(f"Plugin {plugin_id} not found")
            return False
        
        # Remove capabilities
        plugin = self._plugins[plugin_id]
        for cap in plugin.get('capabilities', []):
            cap_name = cap.get('name')
            if cap_name in self._capabilities:
                del self._capabilities[cap_name]
        
        # Remove plugin
        del self._plugins[plugin_id]
        
        # Invalidate cache
        self._invalidate_cache()
        
        logger.info(f"Plugin {plugin_id} unregistered")
        return True
    
    def _invalidate_cache(self) -> None:
        """Invalidate capability resolution cache."""
        self._cache.clear()
        logger.debug("Capability cache invalidated")
    
    def get_registered_capabilities(self) -> List[str]:
        """Get list of all registered capability names."""
        return list(self._capabilities.keys())
    
    def get_plugin_info(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a registered plugin."""
        return self._plugins.get(plugin_id)
    
    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Get audit log of plugin registrations."""
        return [
            {
                'plugin_id': plugin_id,
                'capability_count': len(plugin.get('capabilities', [])),
                'capabilities': [cap.get('name') for cap in plugin.get('capabilities', [])]
            }
            for plugin_id, plugin in self._plugins.items()
        ]
