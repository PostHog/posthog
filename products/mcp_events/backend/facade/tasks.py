"""Celery tasks core's beat schedule registers."""

from products.mcp_events.backend.tasks.tasks import (
    expire_mcp_event_subscriptions as expire_mcp_event_subscriptions,
    reconcile_mcp_event_subscriptions as reconcile_mcp_event_subscriptions,
)
