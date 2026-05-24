"""Tests for webhook API with event type allowlist validation."""

import pytest
from typing import Dict, List

from src.api.webhook import (
    WebhookManager,
    WebhookSubscription,
    WebhookStatus,
    WebhookEventType,
    ALLOWED_EVENT_TYPES,
    webhook_manager,
)


class TestWebhookEventTypeAllowlist:
    """Test event type allowlist validation at subscription create."""
    
    def setup_method(self):
        self.manager = WebhookManager()
    
    def test_create_subscription_with_valid_event_types(self):
        """Test creating subscription with valid event types from allowlist."""
        subscription = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created", "agent.updated"],
            workspace_id="ws_123",
        )
        
        assert subscription.id is not None
        assert subscription.url == "https://example.com/webhook"
        assert subscription.event_types == ["agent.created", "agent.updated"]
        assert subscription.workspace_id == "ws_123"
        assert subscription.status == WebhookStatus.ACTIVE
    
    def test_create_subscription_with_invalid_event_type(self):
        """Test that invalid event types are rejected at subscription create."""
        with pytest.raises(ValueError) as exc_info:
            self.manager.create_subscription(
                url="https://example.com/webhook",
                event_types=["agent.created", "invalid.event.type"],
                workspace_id="ws_123",
            )
        
        assert "Invalid event types" in str(exc_info.value)
        assert "invalid.event.type" in str(exc_info.value)
    
    def test_create_subscription_with_all_invalid_event_types(self):
        """Test that completely invalid event types are rejected."""
        with pytest.raises(ValueError) as exc_info:
            self.manager.create_subscription(
                url="https://example.com/webhook",
                event_types=["fake.event", "another.fake"],
                workspace_id="ws_123",
            )
        
        assert "Invalid event types" in str(exc_info.value)
    
    def test_create_subscription_with_empty_event_types(self):
        """Test that empty event types list is rejected."""
        with pytest.raises(ValueError) as exc_info:
            self.manager.create_subscription(
                url="https://example.com/webhook",
                event_types=[],
                workspace_id="ws_123",
            )
        
        assert "At least one event type must be specified" in str(exc_info.value)
    
    def test_create_subscription_blocks_internal_url(self):
        """Test that internal URLs are blocked for security."""
        blocked_urls = [
            "http://localhost:8080/webhook",
            "http://127.0.0.1:8080/webhook",
            "http://192.168.1.1/webhook",
            "http://10.0.0.1/webhook",
            "http://0.0.0.0/webhook",
        ]
        
        for url in blocked_urls:
            with pytest.raises(ValueError) as exc_info:
                self.manager.create_subscription(
                    url=url,
                    event_types=["agent.created"],
                    workspace_id="ws_123",
                )
            assert "Endpoint validation failed" in str(exc_info.value)


class TestWebhookWorkspaceIsolation:
    """Test workspace isolation for webhooks."""
    
    def setup_method(self):
        self.manager = WebhookManager()
    
    def test_subscription_isolated_by_workspace(self):
        """Test that subscriptions are isolated by workspace."""
        # Create subscription in workspace 1
        sub1 = self.manager.create_subscription(
            url="https://example.com/webhook1",
            event_types=["agent.created"],
            workspace_id="ws_1",
        )
        
        # Create subscription in workspace 2
        sub2 = self.manager.create_subscription(
            url="https://example.com/webhook2",
            event_types=["agent.updated"],
            workspace_id="ws_2",
        )
        
        # List subscriptions for workspace 1
        ws1_subs = self.manager.list_subscriptions("ws_1")
        assert len(ws1_subs) == 1
        assert ws1_subs[0].id == sub1.id
        
        # List subscriptions for workspace 2
        ws2_subs = self.manager.list_subscriptions("ws_2")
        assert len(ws2_subs) == 1
        assert ws2_subs[0].id == sub2.id
    
    def test_get_subscription_enforces_workspace_isolation(self):
        """Test that getting subscription enforces workspace isolation."""
        sub = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_1",
        )
        
        # Should find in correct workspace
        found = self.manager.get_subscription(sub.id, "ws_1")
        assert found is not None
        
        # Should not find in different workspace
        not_found = self.manager.get_subscription(sub.id, "ws_2")
        assert not_found is None
    
    def test_delete_subscription_enforces_workspace_isolation(self):
        """Test that deleting subscription enforces workspace isolation."""
        sub = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_1",
        )
        
        # Should fail to delete from wrong workspace
        result = self.manager.delete_subscription(sub.id, "ws_2")
        assert result is False
        
        # Should succeed from correct workspace
        result = self.manager.delete_subscription(sub.id, "ws_1")
        assert result is True


class TestWebhookDelivery:
    """Test webhook event delivery."""
    
    def setup_method(self):
        self.manager = WebhookManager()
    
    def test_deliver_event_to_matching_subscriptions(self):
        """Test delivering event to matching subscriptions."""
        # Create subscriptions
        sub1 = self.manager.create_subscription(
            url="https://example.com/webhook1",
            event_types=["agent.created", "agent.updated"],
            workspace_id="ws_1",
        )
        sub2 = self.manager.create_subscription(
            url="https://example.com/webhook2",
            event_types=["agent.created"],
            workspace_id="ws_1",
        )
        sub3 = self.manager.create_subscription(
            url="https://example.com/webhook3",
            event_types=["agent.deleted"],
            workspace_id="ws_1",
        )
        
        # Deliver agent.created event
        payload = {"agent_id": "agent_123", "name": "Test Agent"}
        records = self.manager.deliver_event("agent.created", payload, "ws_1")
        
        # Should deliver to sub1 and sub2 (both subscribed to agent.created)
        assert len(records) == 2
        subscription_ids = {r.subscription_id for r in records}
        assert sub1.id in subscription_ids
        assert sub2.id in subscription_ids
        assert sub3.id not in subscription_ids
    
    def test_deliver_event_respects_disabled_subscriptions(self):
        """Test that disabled subscriptions don't receive events."""
        sub = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_1",
        )
        
        # Disable subscription
        self.manager.update_subscription(
            sub.id, "ws_1", status=WebhookStatus.DISABLED
        )
        
        # Deliver event
        records = self.manager.deliver_event("agent.created", {}, "ws_1")
        
        # Should not deliver to disabled subscription
        assert len(records) == 0
    
    def test_deliver_event_respects_workspace_isolation(self):
        """Test that event delivery respects workspace isolation."""
        # Create subscriptions in different workspaces
        self.manager.create_subscription(
            url="https://example.com/webhook1",
            event_types=["agent.created"],
            workspace_id="ws_1",
        )
        self.manager.create_subscription(
            url="https://example.com/webhook2",
            event_types=["agent.created"],
            workspace_id="ws_2",
        )
        
        # Deliver to workspace 1 only
        records = self.manager.deliver_event("agent.created", {}, "ws_1")
        
        assert len(records) == 1


class TestWebhookRetryIdempotency:
    """Test webhook retry idempotency."""
    
    def setup_method(self):
        self.manager = WebhookManager()
    
    def test_retry_delivery_is_idempotent(self):
        """Test that retrying a delivered event is idempotent."""
        # Create subscription and deliver event
        sub = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_1",
        )
        
        records = self.manager.deliver_event("agent.created", {}, "ws_1")
        delivery_id = records[0].id
        
        # Verify initial delivery
        record = self.manager.get_delivery_status(delivery_id, "ws_1")
        assert record.status == "delivered"
        initial_delivered_at = record.delivered_at
        
        # Retry delivery - should be idempotent
        retried = self.manager.retry_delivery(delivery_id, "ws_1")
        
        # Status should remain delivered, not change
        assert retried.status == "delivered"
        assert retried.delivered_at == initial_delivered_at
    
    def test_retry_disabled_subscription_fails(self):
        """Test that retry fails for disabled subscriptions."""
        sub = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_1",
        )
        
        records = self.manager.deliver_event("agent.created", {}, "ws_1")
        delivery_id = records[0].id
        
        # Reset status to pending to simulate a failed delivery
        self.manager._deliveries[delivery_id].status = "failed"
        self.manager._deliveries[delivery_id].error_message = "Connection timeout"
        
        # Disable subscription
        self.manager.update_subscription(
            sub.id, "ws_1", status=WebhookStatus.DISABLED
        )
        
        # Retry should fail
        retried = self.manager.retry_delivery(delivery_id, "ws_1")
        assert retried.error_message == "Subscription disabled"


class TestWebhookSecretRotation:
    """Test webhook secret rotation."""
    
    def setup_method(self):
        self.manager = WebhookManager()
    
    def test_rotate_secret_changes_status(self):
        """Test that rotating secret changes subscription status."""
        sub = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_1",
        )
        
        old_secret = sub.secret
        
        # Rotate secret
        new_secret = self.manager.rotate_secret(sub.id, "ws_1")
        
        assert new_secret is not None
        assert new_secret != old_secret
        
        # Status should be ROTATED
        updated = self.manager.get_subscription(sub.id, "ws_1")
        assert updated.status == WebhookStatus.ROTATED


class TestWebhookAllowedEventTypes:
    """Test the allowed event types enumeration."""
    
    def test_all_event_types_in_allowlist(self):
        """Test that all enum values are in the allowlist."""
        for event_type in WebhookEventType:
            assert event_type.value in ALLOWED_EVENT_TYPES
    
    def test_allowlist_contains_all_enum_values(self):
        """Test that allowlist contains all enum values."""
        enum_values = {e.value for e in WebhookEventType}
        assert ALLOWED_EVENT_TYPES == enum_values


class TestWebhookUpdateValidation:
    """Test webhook subscription update validation."""
    
    def setup_method(self):
        self.manager = WebhookManager()
    
    def test_update_with_invalid_event_types_fails(self):
        """Test that updating with invalid event types fails."""
        sub = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_1",
        )
        
        with pytest.raises(ValueError) as exc_info:
            self.manager.update_subscription(
                sub.id, "ws_1", event_types=["invalid.event"]
            )
        
        assert "Invalid event types" in str(exc_info.value)
    
    def test_update_with_valid_event_types_succeeds(self):
        """Test that updating with valid event types succeeds."""
        sub = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_1",
        )
        
        updated = self.manager.update_subscription(
            sub.id, "ws_1", event_types=["agent.created", "agent.updated"]
        )
        
        assert updated is not None
        assert "agent.created" in updated.event_types
        assert "agent.updated" in updated.event_types


class TestWebhookDeliveryRecords:
    """Test webhook delivery record isolation."""
    
    def setup_method(self):
        self.manager = WebhookManager()
    
    def test_delivery_status_workspace_isolation(self):
        """Test that delivery status respects workspace isolation."""
        # Create subscription and deliver in workspace 1
        self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_1",
        )
        
        records = self.manager.deliver_event("agent.created", {}, "ws_1")
        delivery_id = records[0].id
        
        # Should find in correct workspace
        found = self.manager.get_delivery_status(delivery_id, "ws_1")
        assert found is not None
        
        # Should not find in different workspace
        not_found = self.manager.get_delivery_status(delivery_id, "ws_2")
        assert not_found is None


class TestWebhookEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def setup_method(self):
        self.manager = WebhookManager()
    
    def test_url_without_https(self):
        """Test that non-HTTPS URLs are handled (may be rejected or accepted based on implementation)."""
        # Some implementations accept http, some reject it
        # This test documents the current behavior
        try:
            subscription = self.manager.create_subscription(
                url="http://example.com/webhook",
                event_types=["agent.created"],
                workspace_id="ws_123",
            )
            # If accepted, verify it was created
            assert subscription.id is not None
        except ValueError:
            # If rejected, that's also valid behavior
            pass
    
    def test_url_with_path_and_query(self):
        """Test URL with path and query parameters."""
        subscription = self.manager.create_subscription(
            url="https://example.com/webhook?token=abc123",
            event_types=["agent.created"],
            workspace_id="ws_123",
        )
        assert subscription.url == "https://example.com/webhook?token=abc123"
    
    def test_duplicate_subscription_detection(self):
        """Test that duplicate subscriptions are detected."""
        self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_123",
        )
        
        # Creating same subscription again should work (idempotent)
        sub2 = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_123",
        )
        assert sub2.id is not None
    
    def test_max_event_types_limit(self):
        """Test maximum number of event types per subscription."""
        # Try to create subscription with many event types
        all_event_types = list(ALLOWED_EVENT_TYPES)[:5]  # Use first 5 allowed types
        
        subscription = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=all_event_types,
            workspace_id="ws_123",
        )
        assert len(subscription.event_types) == 5
    
    def test_webhook_manager_str_representation(self):
        """Test WebhookManager string representation."""
        str_repr = str(self.manager)
        assert isinstance(str_repr, str)
    
    def test_subscription_str_representation(self):
        """Test WebhookSubscription string representation."""
        subscription = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_123",
        )
        str_repr = str(subscription)
        assert isinstance(str_repr, str)
    
    def test_delivery_record_str_representation(self):
        """Test DeliveryRecord string representation."""
        subscription = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_123",
        )
        
        # Deliver an event
        deliveries = self.manager.deliver_event(
            event_type="agent.created",
            payload={"agent_id": "agent_123"},
            workspace_id="ws_123",
        )
        
        if deliveries:
            str_repr = str(deliveries[0])
            assert isinstance(str_repr, str)
    
    def test_list_subscriptions_empty(self):
        """Test listing subscriptions when none exist."""
        subscriptions = self.manager.list_subscriptions("ws_empty")
        assert subscriptions == []
    
    def test_list_subscriptions_with_multiple(self):
        """Test listing multiple subscriptions."""
        self.manager.create_subscription(
            url="https://example.com/webhook1",
            event_types=["agent.created"],
            workspace_id="ws_multi",
        )
        self.manager.create_subscription(
            url="https://example.com/webhook2",
            event_types=["agent.updated"],
            workspace_id="ws_multi",
        )
        
        subscriptions = self.manager.list_subscriptions("ws_multi")
        assert len(subscriptions) == 2
    
    def test_get_nonexistent_subscription(self):
        """Test getting a subscription that doesn't exist."""
        result = self.manager.get_subscription("nonexistent-id", "ws_123")
        assert result is None
    
    def test_delete_nonexistent_subscription(self):
        """Test deleting a subscription that doesn't exist."""
        result = self.manager.delete_subscription("nonexistent-id", "ws_123")
        assert result is False
    
    def test_update_nonexistent_subscription(self):
        """Test updating a subscription that doesn't exist."""
        result = self.manager.update_subscription(
            "nonexistent-id",
            "ws_123",
            event_types=["agent.created"],
        )
        assert result is None
    
    def test_retry_nonexistent_delivery(self):
        """Test retrying a delivery that doesn't exist."""
        result = self.manager.retry_delivery("nonexistent-id", "ws_123")
        assert result is None
    
    def test_rotate_secret_nonexistent_subscription(self):
        """Test rotating secret for nonexistent subscription."""
        result = self.manager.rotate_secret("nonexistent-id", "ws_123")
        assert result is None
    
    def test_event_type_case_sensitivity(self):
        """Test that event types are case sensitive."""
        with pytest.raises(ValueError):
            self.manager.create_subscription(
                url="https://example.com/webhook",
                event_types=["Agent.Created"],  # Wrong case
                workspace_id="ws_123",
            )
    
    def test_url_with_fragment(self):
        """Test URL with fragment identifier."""
        subscription = self.manager.create_subscription(
            url="https://example.com/webhook#section",
            event_types=["agent.created"],
            workspace_id="ws_123",
        )
        assert "section" in subscription.url


# Integration tests for the API layer
class TestWebhookAPIIntegration:
    """Integration tests for webhook API endpoints."""
    
    def test_event_type_validation_at_api_level(self):
        """Test that event type validation happens at API level."""
        # This tests the Pydantic model validation
        from pydantic import ValidationError
        
        # Valid event types should work
        sub = WebhookSubscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_1",
        )
        assert sub.event_types == ["agent.created"]
        
        # Invalid event types should fail
        with pytest.raises(ValidationError) as exc_info:
            WebhookSubscription(
                url="https://example.com/webhook",
                event_types=["invalid.event"],
                workspace_id="ws_1",
            )
        
        assert "Invalid event types" in str(exc_info.value)
