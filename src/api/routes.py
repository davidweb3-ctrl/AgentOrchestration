"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus
from src.api.webhook import (
    webhook_manager,
    WebhookSubscription,
    WebhookStatus,
    WebhookEventType,
    ALLOWED_EVENT_TYPES,
)

router = APIRouter()
registry = AgentRegistry()


@router.get("/agents")
async def list_agents(status: Optional[str] = None, group: Optional[str] = None):
    status_filter = AgentStatus(status) if status else None
    return {"agents": registry.list(status=status_filter, group=group)}


@router.post("/agents")
async def register_agent(name: str, agent_type: str, config: Optional[Dict] = None):
    agent_id = registry.register(name, agent_type, config)
    return {"agent_id": agent_id, "status": "registered"}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    if not registry.delete(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "deleted"}


@router.post("/agents/{agent_id}/start")
async def start_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.RUNNING):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "started"}


@router.post("/agents/{agent_id}/stop")
async def stop_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.PAUSED):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "stopped"}


@router.get("/agents/count")
async def agent_count():
    return {"count": registry.count()}


# Webhook API routes
@router.post("/webhooks/subscriptions")
async def create_webhook_subscription(
    url: str,
    event_types: List[str],
    workspace_id: str,
    secret: Optional[str] = None,
):
    """
    Create a new webhook subscription with event type allowlist validation.
    
    Validates event types against allowlist before creating subscription.
    """
    try:
        subscription = webhook_manager.create_subscription(
            url=url,
            event_types=event_types,
            workspace_id=workspace_id,
            secret=secret,
        )
        return {
            "subscription_id": subscription.id,
            "url": subscription.url,
            "event_types": subscription.event_types,
            "status": subscription.status,
            "created_at": subscription.created_at,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/webhooks/subscriptions")
async def list_webhook_subscriptions(workspace_id: str):
    """List all webhook subscriptions for a workspace."""
    subscriptions = webhook_manager.list_subscriptions(workspace_id)
    return {
        "subscriptions": [
            {
                "id": s.id,
                "url": s.url,
                "event_types": s.event_types,
                "status": s.status,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
            for s in subscriptions
        ]
    }


@router.get("/webhooks/subscriptions/{subscription_id}")
async def get_webhook_subscription(subscription_id: str, workspace_id: str):
    """Get a specific webhook subscription."""
    subscription = webhook_manager.get_subscription(subscription_id, workspace_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {
        "id": subscription.id,
        "url": subscription.url,
        "event_types": subscription.event_types,
        "status": subscription.status,
        "workspace_id": subscription.workspace_id,
        "created_at": subscription.created_at,
        "updated_at": subscription.updated_at,
    }


@router.put("/webhooks/subscriptions/{subscription_id}")
async def update_webhook_subscription(
    subscription_id: str,
    workspace_id: str,
    event_types: Optional[List[str]] = None,
    url: Optional[str] = None,
    status: Optional[str] = None,
):
    """Update a webhook subscription with validation."""
    try:
        webhook_status = WebhookStatus(status) if status else None
        subscription = webhook_manager.update_subscription(
            subscription_id=subscription_id,
            workspace_id=workspace_id,
            event_types=event_types,
            url=url,
            status=webhook_status,
        )
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return {
            "id": subscription.id,
            "url": subscription.url,
            "event_types": subscription.event_types,
            "status": subscription.status,
            "updated_at": subscription.updated_at,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/webhooks/subscriptions/{subscription_id}")
async def delete_webhook_subscription(subscription_id: str, workspace_id: str):
    """Delete a webhook subscription."""
    if not webhook_manager.delete_subscription(subscription_id, workspace_id):
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "deleted"}


@router.post("/webhooks/subscriptions/{subscription_id}/rotate")
async def rotate_webhook_secret(subscription_id: str, workspace_id: str):
    """Rotate webhook secret."""
    new_secret = webhook_manager.rotate_secret(subscription_id, workspace_id)
    if not new_secret:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"new_secret": new_secret}


@router.post("/webhooks/deliver")
async def deliver_webhook_event(
    event_type: str,
    payload: Dict,
    workspace_id: str,
):
    """Deliver a webhook event to all matching subscriptions."""
    # Validate event type against allowlist
    if event_type not in ALLOWED_EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event type: {event_type}. Allowed: {ALLOWED_EVENT_TYPES}"
        )
    
    records = webhook_manager.deliver_event(event_type, payload, workspace_id)
    return {
        "deliveries": [
            {
                "id": r.id,
                "subscription_id": r.subscription_id,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in records
        ]
    }


@router.get("/webhooks/deliveries/{delivery_id}")
async def get_delivery_status(delivery_id: str, workspace_id: str):
    """Get the status of a webhook delivery."""
    record = webhook_manager.get_delivery_status(delivery_id, workspace_id)
    if not record:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return {
        "id": record.id,
        "subscription_id": record.subscription_id,
        "event_type": record.event_type,
        "status": record.status,
        "created_at": record.created_at,
        "delivered_at": record.delivered_at,
        "retry_count": record.retry_count,
        "error_message": record.error_message,
    }


@router.post("/webhooks/deliveries/{delivery_id}/retry")
async def retry_webhook_delivery(delivery_id: str, workspace_id: str):
    """Retry a failed webhook delivery with idempotency."""
    record = webhook_manager.retry_delivery(delivery_id, workspace_id)
    if not record:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return {
        "id": record.id,
        "status": record.status,
        "retry_count": record.retry_count,
        "delivered_at": record.delivered_at,
        "error_message": record.error_message,
    }


@router.get("/webhooks/event-types")
async def list_webhook_event_types():
    """List all allowed webhook event types."""
    return {
        "event_types": list(ALLOWED_EVENT_TYPES),
        "descriptions": {
            e.value: e.name.lower().replace("_", " ")
            for e in WebhookEventType
        }
    }

# 2019-03-18T11:10:18 update

# 2019-04-22T13:58:05 update

# 2019-05-28T08:52:40 update

# 2019-06-13T19:27:11 update

# 2019-06-25T18:52:04 update

# 2019-06-26T17:23:40 update

# 2019-07-24T12:38:12 update

# 2019-08-06T17:13:22 update

# 2019-09-26T19:27:40 update

# 2019-11-08T15:48:07 update

# 2019-12-05T16:07:01 update

# 2020-01-17T17:50:06 update

# 2020-04-24T17:12:53 update

# 2020-07-21T19:32:14 update

# 2020-07-21T20:23:54 update

# 2020-08-14T20:37:18 update

# 2020-11-05T16:47:32 update

# 2021-03-11T12:52:51 update

# 2021-03-15T12:40:28 update

# 2021-03-19T19:24:45 update

# 2021-05-07T14:43:25 update

# 2021-05-12T12:11:05 update

# 2021-05-26T19:45:39 update

# 2021-06-29T19:14:28 update

# 2021-07-09T17:57:49 update

# 2021-07-19T08:20:34 update

# 2021-07-23T15:35:00 update

# 2021-07-26T09:55:35 update

# 2021-11-01T20:50:23 update

# 2022-02-04T09:23:08 update

# 2022-02-14T15:58:17 update

# 2022-02-28T09:52:05 update

# 2022-05-19T16:28:06 update

# 2022-05-30T15:01:44 update

# 2022-07-31T11:24:57 update

# 2022-08-09T15:47:57 update

# 2022-08-19T12:51:59 update

# 2022-11-02T08:06:45 update

# 2022-11-21T14:12:56 update

# 2023-01-13T12:25:51 update

# 2023-03-31T14:11:34 update

# 2023-04-03T20:57:22 update

# 2023-04-28T19:01:38 update

# 2023-07-18T16:47:22 update

# 2023-09-28T18:50:58 update

# 2023-10-02T13:22:15 update

# 2023-10-23T10:46:19 update

# 2023-11-02T16:52:55 update

# 2023-12-08T17:38:20 update

# 2023-12-11T10:59:19 update

# 2024-01-15T16:27:41 update

# 2024-02-09T11:56:21 update

# 2024-02-15T16:47:43 update

# 2024-03-26T08:08:33 update

# 2024-07-11T15:59:46 update

# 2024-09-04T17:13:05 update

# 2024-09-20T11:28:38 update

# 2024-12-02T16:42:53 update

# 2025-01-15T12:12:38 update

# 2025-02-05T09:08:36 update

# 2025-05-16T19:40:31 update

# 2025-06-13T13:20:50 update

# 2025-08-13T12:22:26 update

# 2025-09-01T12:30:44 update

# 2025-11-06T12:23:44 update

# 2025-12-26T08:40:45 update

# 2026-04-08T19:23:48 update

# 2026-04-09T20:30:37 update

# 2026-05-13T11:36:25 update
