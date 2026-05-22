"""Webhook API for subscription management and event delivery."""

import hashlib
import hmac
import logging
import secrets
import time
from typing import Dict, List, Optional, Set
from enum import Enum

from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)


class WebhookStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ROTATED = "rotated"


class WebhookEventType(str, Enum):
    """Allowed event types for webhook subscriptions."""
    AGENT_CREATED = "agent.created"
    AGENT_UPDATED = "agent.updated"
    AGENT_DELETED = "agent.deleted"
    AGENT_STARTED = "agent.started"
    AGENT_STOPPED = "agent.stopped"
    TASK_CREATED = "task.created"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"


# Define the allowlist of valid event types
ALLOWED_EVENT_TYPES: Set[str] = {e.value for e in WebhookEventType}


class WebhookSubscription(BaseModel):
    """Webhook subscription model with event type allowlist validation."""
    
    id: Optional[str] = None
    url: str = Field(..., description="Webhook endpoint URL")
    event_types: List[str] = Field(..., description="List of event types to subscribe to")
    secret: Optional[str] = Field(None, description="Secret for HMAC signature")
    status: WebhookStatus = Field(default=WebhookStatus.ACTIVE)
    workspace_id: str = Field(..., description="Workspace ID for isolation")
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    retry_count: int = Field(default=0)
    max_retries: int = Field(default=3)
    
    @validator("event_types")
    def validate_event_types(cls, v: List[str]) -> List[str]:
        """Validate that all event types are in the allowlist."""
        if not v:
            raise ValueError("At least one event type must be specified")
        
        invalid_types = set(v) - ALLOWED_EVENT_TYPES
        if invalid_types:
            raise ValueError(
                f"Invalid event types: {invalid_types}. "
                f"Allowed types: {ALLOWED_EVENT_TYPES}"
            )
        return v
    
    @validator("url")
    def validate_url(cls, v: str) -> str:
        """Validate URL format."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v
    
    class Config:
        validate_assignment = True


class WebhookDeliveryRecord(BaseModel):
    """Record of a webhook delivery attempt."""
    
    id: str
    subscription_id: str
    event_type: str
    payload: Dict
    status: str  # "pending", "delivered", "failed"
    created_at: float
    delivered_at: Optional[float] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    signature: Optional[str] = None


class WebhookManager:
    """Manages webhook subscriptions and event delivery."""
    
    def __init__(self):
        self._subscriptions: Dict[str, WebhookSubscription] = {}
        self._deliveries: Dict[str, WebhookDeliveryRecord] = {}
        self._workspace_subscriptions: Dict[str, Set[str]] = {}
    
    def create_subscription(
        self,
        url: str,
        event_types: List[str],
        workspace_id: str,
        secret: Optional[str] = None,
    ) -> WebhookSubscription:
        """
        Create a new webhook subscription with event type allowlist validation.
        
        Args:
            url: Webhook endpoint URL
            event_types: List of event types to subscribe to
            workspace_id: Workspace ID for isolation
            secret: Optional secret for HMAC signature
            
        Returns:
            WebhookSubscription: The created subscription
            
        Raises:
            ValueError: If event types are not in allowlist
        """
        # Validate event types against allowlist before creating
        invalid_types = set(event_types) - ALLOWED_EVENT_TYPES
        if invalid_types:
            logger.warning(
                f"Subscription rejected: invalid event types {invalid_types}"
            )
            raise ValueError(
                f"Invalid event types: {invalid_types}. "
                f"Allowed types: {ALLOWED_EVENT_TYPES}"
            )
        
        # Validate endpoint before persistence
        if not self._validate_endpoint(url):
            raise ValueError(f"Endpoint validation failed for URL: {url}")
        
        subscription_id = secrets.token_urlsafe(16)
        now = time.time()
        
        subscription = WebhookSubscription(
            id=subscription_id,
            url=url,
            event_types=event_types,
            workspace_id=workspace_id,
            secret=secret or secrets.token_urlsafe(32),
            status=WebhookStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        
        # Store subscription
        self._subscriptions[subscription_id] = subscription
        
        # Index by workspace for isolation
        if workspace_id not in self._workspace_subscriptions:
            self._workspace_subscriptions[workspace_id] = set()
        self._workspace_subscriptions[workspace_id].add(subscription_id)
        
        logger.info(f"Created webhook subscription {subscription_id} for workspace {workspace_id}")
        return subscription
    
    def _validate_endpoint(self, url: str) -> bool:
        """Validate webhook endpoint before persistence."""
        # Basic URL validation
        if not url or not url.startswith(("http://", "https://")):
            return False
        
        # Block internal/private IP ranges for security
        blocked_prefixes = [
            "http://localhost",
            "https://localhost",
            "http://127.",
            "https://127.",
            "http://192.168.",
            "http://10.",
            "http://172.16.",
            "http://0.",
            "https://0.",
        ]
        
        for prefix in blocked_prefixes:
            if url.startswith(prefix):
                logger.warning(f"Blocked internal URL: {url}")
                return False
        
        return True
    
    def get_subscription(self, subscription_id: str, workspace_id: str) -> Optional[WebhookSubscription]:
        """Get subscription with workspace isolation check."""
        subscription = self._subscriptions.get(subscription_id)
        if subscription and subscription.workspace_id == workspace_id:
            return subscription
        return None
    
    def list_subscriptions(self, workspace_id: str) -> List[WebhookSubscription]:
        """List all subscriptions for a workspace."""
        subscription_ids = self._workspace_subscriptions.get(workspace_id, set())
        return [
            self._subscriptions[sid]
            for sid in subscription_ids
            if sid in self._subscriptions
        ]
    
    def update_subscription(
        self,
        subscription_id: str,
        workspace_id: str,
        event_types: Optional[List[str]] = None,
        url: Optional[str] = None,
        status: Optional[WebhookStatus] = None,
    ) -> Optional[WebhookSubscription]:
        """Update subscription with validation."""
        subscription = self.get_subscription(subscription_id, workspace_id)
        if not subscription:
            return None
        
        # Validate event types if provided
        if event_types is not None:
            invalid_types = set(event_types) - ALLOWED_EVENT_TYPES
            if invalid_types:
                raise ValueError(f"Invalid event types: {invalid_types}")
            subscription.event_types = event_types
        
        if url is not None:
            if not self._validate_endpoint(url):
                raise ValueError(f"Endpoint validation failed for URL: {url}")
            subscription.url = url
        
        if status is not None:
            subscription.status = status
        
        subscription.updated_at = time.time()
        return subscription
    
    def delete_subscription(self, subscription_id: str, workspace_id: str) -> bool:
        """Delete subscription with workspace isolation."""
        subscription = self.get_subscription(subscription_id, workspace_id)
        if not subscription:
            return False
        
        del self._subscriptions[subscription_id]
        self._workspace_subscriptions[workspace_id].discard(subscription_id)
        return True
    
    def rotate_secret(self, subscription_id: str, workspace_id: str) -> Optional[str]:
        """Rotate webhook secret."""
        subscription = self.get_subscription(subscription_id, workspace_id)
        if not subscription:
            return None
        
        new_secret = secrets.token_urlsafe(32)
        subscription.secret = new_secret
        subscription.status = WebhookStatus.ROTATED
        subscription.updated_at = time.time()
        return new_secret
    
    def deliver_event(
        self,
        event_type: str,
        payload: Dict,
        workspace_id: str,
    ) -> List[WebhookDeliveryRecord]:
        """
        Deliver event to all matching subscriptions in a workspace.
        
        Args:
            event_type: Type of event
            payload: Event payload
            workspace_id: Workspace ID for isolation
            
        Returns:
            List of delivery records
        """
        records = []
        subscriptions = self.list_subscriptions(workspace_id)
        
        for subscription in subscriptions:
            # Check if subscription is active
            if subscription.status != WebhookStatus.ACTIVE:
                logger.debug(f"Skipping inactive subscription {subscription.id}")
                continue
            
            # Check if event type is in subscription's allowlist
            if event_type not in subscription.event_types:
                continue
            
            # Create delivery record
            delivery_id = secrets.token_urlsafe(16)
            signature = self._generate_signature(subscription.secret, payload)
            
            record = WebhookDeliveryRecord(
                id=delivery_id,
                subscription_id=subscription.id,
                event_type=event_type,
                payload=payload,
                status="pending",
                created_at=time.time(),
                signature=signature,
            )
            
            self._deliveries[delivery_id] = record
            records.append(record)
            
            # Attempt delivery (async in real implementation)
            self._attempt_delivery(record, subscription)
        
        return records
    
    def _generate_signature(self, secret: str, payload: Dict) -> str:
        """Generate HMAC signature for webhook payload."""
        import json
        payload_bytes = json.dumps(payload, sort_keys=True).encode()
        signature = hmac.new(
            secret.encode(),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"
    
    def _attempt_delivery(
        self,
        record: WebhookDeliveryRecord,
        subscription: WebhookSubscription,
    ) -> None:
        """Attempt webhook delivery with idempotency check."""
        # Check if already delivered (idempotency)
        if record.status == "delivered":
            logger.info(f"Delivery {record.id} already completed")
            return
        
        # In a real implementation, this would make HTTP request
        # For now, simulate delivery
        logger.info(f"Delivering event {record.event_type} to {subscription.url}")
        
        # Update retry count
        record.retry_count += 1
        
        # Simulate delivery logic
        if record.retry_count <= subscription.max_retries:
            record.status = "delivered"
            record.delivered_at = time.time()
        else:
            record.status = "failed"
            record.error_message = "Max retries exceeded"
    
    def retry_delivery(self, delivery_id: str, workspace_id: str) -> Optional[WebhookDeliveryRecord]:
        """Retry a failed delivery with idempotency."""
        record = self._deliveries.get(delivery_id)
        if not record:
            return None
        
        # Verify workspace isolation
        subscription = self._subscriptions.get(record.subscription_id)
        if not subscription or subscription.workspace_id != workspace_id:
            return None
        
        # Idempotency: check if already delivered
        if record.status == "delivered":
            logger.info(f"Delivery {delivery_id} already completed, skipping retry")
            return record
        
        # Check subscription status
        if subscription.status == WebhookStatus.DISABLED:
            logger.warning(f"Cannot retry: subscription {subscription.id} is disabled")
            record.error_message = "Subscription disabled"
            return record
        
        # Attempt retry
        self._attempt_delivery(record, subscription)
        return record
    
    def get_delivery_status(self, delivery_id: str, workspace_id: str) -> Optional[WebhookDeliveryRecord]:
        """Get delivery status with workspace isolation."""
        record = self._deliveries.get(delivery_id)
        if not record:
            return None
        
        # Verify workspace isolation
        subscription = self._subscriptions.get(record.subscription_id)
        if not subscription or subscription.workspace_id != workspace_id:
            return None
        
        return record


# Global webhook manager instance
webhook_manager = WebhookManager()
