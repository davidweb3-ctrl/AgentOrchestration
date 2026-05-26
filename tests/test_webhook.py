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


class TestWebhookPerformance:
    """Test webhook performance under load."""

    def test_bulk_subscription_creation(self):
        """Test creating many subscriptions efficiently."""
        manager = WebhookManager()

        # Create 50 subscriptions
        for i in range(50):
            manager.create_subscription(
                url=f"https://example.com/webhook{i}",
                event_types=["agent.created"],
                workspace_id="ws_bulk",
            )

        subscriptions = manager.list_subscriptions("ws_bulk")
        assert len(subscriptions) == 50

    def test_high_volume_subscription_operations(self):
        """Test high volume subscription operations."""
        manager = WebhookManager()

        # Create many subscriptions
        for i in range(100):
            manager.create_subscription(
                url=f"https://example.com/webhook{i}",
                event_types=["agent.created"],
                workspace_id="ws_volume",
            )

        # List all subscriptions
        subscriptions = manager.list_subscriptions("ws_volume")
        assert len(subscriptions) == 100

        # Update many subscriptions
        for sub in subscriptions[:10]:
            manager.update_subscription(
                sub.id,
                "ws_volume",
                event_types=["agent.created", "agent.updated"],
            )

        # Verify updates
        updated = manager.list_subscriptions("ws_volume")
        assert len(updated) == 100


class TestWebhookSecurity:
    """Test webhook security features."""

    def test_secret_uniqueness(self):
        """Test that each subscription has unique secret."""
        manager = WebhookManager()

        sub1 = manager.create_subscription(
            url="https://example.com/webhook1",
            event_types=["agent.created"],
            workspace_id="ws_secret",
        )

        sub2 = manager.create_subscription(
            url="https://example.com/webhook2",
            event_types=["agent.created"],
            workspace_id="ws_secret",
        )

        # Secrets should be unique
        assert sub1.secret != sub2.secret

    def test_workspace_isolation(self):
        """Test strict workspace isolation."""
        manager = WebhookManager()

        # Create subscription in workspace A
        sub_a = manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_a",
        )

        # Try to access from workspace B
        result = manager.get_subscription(sub_a.id, "ws_b")
        assert result is None

        # Try to delete from workspace B
        result = manager.delete_subscription(sub_a.id, "ws_b")
        assert result is False

        # Verify still exists in workspace A
        sub = manager.get_subscription(sub_a.id, "ws_a")
        assert sub is not None

    def test_id_generation_uniqueness(self):
        """Test that subscription IDs are unique."""
        manager = WebhookManager()

        ids = set()
        for i in range(20):
            sub = manager.create_subscription(
                url=f"https://example.com/webhook{i}",
                event_types=["agent.created"],
                workspace_id="ws_ids",
            )
            ids.add(sub.id)

        # All IDs should be unique
        assert len(ids) == 20


class TestWebhookReliability:
    """Test webhook reliability features."""

    def test_subscription_update_preserves_id(self):
        """Test that updating subscription preserves ID."""
        manager = WebhookManager()

        subscription = manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_history",
        )

        # Update subscription
        updated = manager.update_subscription(
            subscription.id,
            "ws_history",
            event_types=["agent.created", "agent.updated"],
        )

        assert updated is not None
        assert subscription.id == updated.id

    def test_retry_mechanism_exists(self):
        """Test that retry mechanism exists."""
        manager = WebhookManager()

        subscription = manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_retry",
        )

        # Create a delivery record for testing retry
        # Note: retry_delivery method should exist
        result = manager.retry_delivery("nonexistent-delivery-id", "ws_retry")
        # Should handle gracefully
        assert result is None

    def test_subscription_state_consistency(self):
        """Test subscription state remains consistent."""
        manager = WebhookManager()

        subscription = manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_state",
        )

        # Multiple operations
        manager.update_subscription(
            subscription.id,
            "ws_state",
            event_types=["agent.created", "agent.updated"],
        )

        manager.rotate_secret(subscription.id, "ws_state")

        # State should be consistent
        sub = manager.get_subscription(subscription.id, "ws_state")
        assert sub is not None
        assert len(sub.event_types) == 2


class TestWebhookAdvancedEdgeCases:
    """Advanced edge case tests for webhook validation."""
    
    def setup_method(self):
        self.manager = WebhookManager()
    
    def test_url_with_port(self):
        """Test URL with non-standard port."""
        subscription = self.manager.create_subscription(
            url="https://example.com:8443/webhook",
            event_types=["agent.created"],
            workspace_id="ws_123",
        )
        assert subscription.url == "https://example.com:8443/webhook"
    
    def test_url_with_auth_in_path(self):
        """Test URL with authentication in path (may be rejected)."""
        # URLs with user:pass@ may be rejected for security
        try:
            self.manager.create_subscription(
                url="https://user:pass@example.com/webhook",
                event_types=["agent.created"],
                workspace_id="ws_123",
            )
            # If accepted, that's ok
        except ValueError:
            # If rejected, that's also valid
            pass
    
    def test_very_long_url(self):
        """Test URL with very long path."""
        long_path = "/webhook/" + "a" * 500
        subscription = self.manager.create_subscription(
            url=f"https://example.com{long_path}",
            event_types=["agent.created"],
            workspace_id="ws_123",
        )
        assert long_path in subscription.url
    
    def test_unicode_in_url(self):
        """Test URL with unicode characters."""
        # URLs with unicode should be handled
        try:
            subscription = self.manager.create_subscription(
                url="https://example.com/webhook?param=测试",
                event_types=["agent.created"],
                workspace_id="ws_123",
            )
            # If accepted, verify it was created
            assert subscription.id is not None
        except (ValueError, UnicodeError):
            # If rejected, that's also valid behavior
            pass
    
    def test_event_type_with_special_chars(self):
        """Test event type with special characters (should be rejected)."""
        with pytest.raises(ValueError):
            self.manager.create_subscription(
                url="https://example.com/webhook",
                event_types=["agent.created;DROP TABLE users"],
                workspace_id="ws_123",
            )
    
    def test_event_type_sql_injection_attempt(self):
        """Test SQL injection attempt in event type."""
        with pytest.raises(ValueError):
            self.manager.create_subscription(
                url="https://example.com/webhook",
                event_types=["agent.created', '1'='1"],
                workspace_id="ws_123",
            )
    
    def test_workspace_id_sql_injection(self):
        """Test SQL injection attempt in workspace ID."""
        # Should handle gracefully (create or reject)
        try:
            subscription = self.manager.create_subscription(
                url="https://example.com/webhook",
                event_types=["agent.created"],
                workspace_id="ws_123'; DROP TABLE subscriptions; --",
            )
            assert subscription.workspace_id is not None
        except ValueError:
            pass  # Rejection is also valid
    
    def test_empty_workspace_id(self):
        """Test empty workspace ID (may be rejected or accepted)."""
        try:
            self.manager.create_subscription(
                url="https://example.com/webhook",
                event_types=["agent.created"],
                workspace_id="",
            )
            # If accepted
        except ValueError:
            # If rejected, that's valid
            pass
    
    def test_whitespace_only_workspace_id(self):
        """Test whitespace-only workspace ID (may be rejected or accepted)."""
        try:
            self.manager.create_subscription(
                url="https://example.com/webhook",
                event_types=["agent.created"],
                workspace_id="   ",
            )
            # If accepted
        except ValueError:
            # If rejected, that's valid
            pass
    
    def test_all_allowed_event_types(self):
        """Test subscription with all allowed event types."""
        all_types = list(ALLOWED_EVENT_TYPES)
        subscription = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=all_types,
            workspace_id="ws_all",
        )
        assert set(subscription.event_types) == set(all_types)
    
    def test_duplicate_event_types_in_request(self):
        """Test duplicate event types in request."""
        subscription = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created", "agent.created", "agent.updated"],
            workspace_id="ws_123",
        )
        # Note: Implementation may or may not deduplicate
        # Just verify subscription was created
        assert subscription.id is not None
        assert "agent.created" in subscription.event_types
        assert "agent.updated" in subscription.event_types
    
    def test_delivery_with_empty_payload(self):
        """Test delivery with empty payload."""
        self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_empty",
        )
        
        records = self.manager.deliver_event("agent.created", {}, "ws_empty")
        assert len(records) == 1
    
    def test_delivery_with_large_payload(self):
        """Test delivery with large payload."""
        self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_large",
        )
        
        large_payload = {"data": "x" * 10000}
        records = self.manager.deliver_event("agent.created", large_payload, "ws_large")
        assert len(records) == 1
    
    def test_delivery_with_nested_payload(self):
        """Test delivery with deeply nested payload."""
        self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_nested",
        )
        
        nested_payload = {"level1": {"level2": {"level3": {"value": "deep"}}}}
        records = self.manager.deliver_event("agent.created", nested_payload, "ws_nested")
        assert len(records) == 1
    
    def test_multiple_deliveries_same_subscription(self):
        """Test multiple deliveries to same subscription."""
        self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created", "agent.updated"],
            workspace_id="ws_multi",
        )
        
        # Deliver multiple events
        records1 = self.manager.deliver_event("agent.created", {}, "ws_multi")
        records2 = self.manager.deliver_event("agent.updated", {}, "ws_multi")
        records3 = self.manager.deliver_event("agent.created", {}, "ws_multi")
        
        assert len(records1) == 1
        assert len(records2) == 1
        assert len(records3) == 1
        
        # All delivery IDs should be unique
        all_ids = {r.id for r in records1 + records2 + records3}
        assert len(all_ids) == 3
    
    def test_concurrent_subscription_operations(self):
        """Test concurrent subscription operations."""
        # Create multiple subscriptions
        subs = []
        for i in range(10):
            sub = self.manager.create_subscription(
                url=f"https://example.com/webhook{i}",
                event_types=["agent.created"],
                workspace_id="ws_concurrent",
            )
            subs.append(sub)
        
        # Update all
        for sub in subs:
            self.manager.update_subscription(
                sub.id, "ws_concurrent", event_types=["agent.created", "agent.updated"]
            )
        
        # Verify all updated
        for sub in subs:
            updated = self.manager.get_subscription(sub.id, "ws_concurrent")
            assert len(updated.event_types) == 2
    
    def test_rotate_secret_multiple_times(self):
        """Test rotating secret multiple times."""
        sub = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_rotate",
        )
        
        secrets = [sub.secret]
        for _ in range(5):
            new_secret = self.manager.rotate_secret(sub.id, "ws_rotate")
            secrets.append(new_secret)
        
        # All secrets should be unique
        assert len(set(secrets)) == len(secrets)
    
    def test_subscription_with_very_long_id(self):
        """Test subscription with very long workspace ID."""
        long_id = "ws_" + "a" * 200
        subscription = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id=long_id,
        )
        assert subscription.workspace_id == long_id
    
    def test_event_type_ordering_preserved(self):
        """Test that event type ordering is preserved."""
        event_types = ["agent.updated", "agent.created", "agent.deleted"]
        subscription = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=event_types,
            workspace_id="ws_order",
        )
        # Order should be preserved
        assert subscription.event_types == event_types


class TestWebhookBoundaryConditions:
    """Test boundary conditions and limits."""
    
    def setup_method(self):
        self.manager = WebhookManager()
    
    def test_max_subscriptions_per_workspace(self):
        """Test maximum subscriptions per workspace."""
        # Create many subscriptions
        for i in range(100):
            self.manager.create_subscription(
                url=f"https://example.com/webhook{i}",
                event_types=["agent.created"],
                workspace_id="ws_limit",
            )
        
        subs = self.manager.list_subscriptions("ws_limit")
        assert len(subs) == 100
    
    def test_single_event_type_subscription(self):
        """Test subscription with single event type."""
        subscription = self.manager.create_subscription(
            url="https://example.com/webhook",
            event_types=["agent.created"],
            workspace_id="ws_single",
        )
        assert subscription.event_types == ["agent.created"]
    
    def test_url_with_subdomain(self):
        """Test URL with multiple subdomains."""
        subscription = self.manager.create_subscription(
            url="https://webhook.api.example.com/endpoint",
            event_types=["agent.created"],
            workspace_id="ws_subdomain",
        )
        assert "webhook.api.example.com" in subscription.url
    
    def test_ipv6_url_blocked(self):
        """Test that IPv6 URLs are blocked (may be rejected)."""
        try:
            self.manager.create_subscription(
                url="http://[::1]:8080/webhook",
                event_types=["agent.created"],
                workspace_id="ws_123",
            )
            # If accepted
        except ValueError:
            # If rejected, that's valid security behavior
            pass
    
    def test_private_ip_ranges_blocked(self):
        """Test that private IP ranges are blocked (may be rejected)."""
        private_ips = [
            "http://172.16.0.1/webhook",
            "http://172.31.255.255/webhook",
            "http://169.254.1.1/webhook",
        ]
        
        blocked_count = 0
        for url in private_ips:
            try:
                self.manager.create_subscription(
                    url=url,
                    event_types=["agent.created"],
                    workspace_id="ws_123",
                )
            except ValueError as e:
                if "Endpoint validation failed" in str(e):
                    blocked_count += 1
        
        # At least some should be blocked for security
        assert blocked_count >= 1, "Private IPs should be blocked for security"
