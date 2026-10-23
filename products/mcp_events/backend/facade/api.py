"""
Facade for mcp_events.

The only module other products may import. Takes and returns contracts; never ORM instances or DRF classes.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import JsonValue

from posthog.models import Team, User

from products.mcp_events.backend.facade import contracts
from products.mcp_events.backend.logic.callback import signing_key, validate_callback_url
from products.mcp_events.backend.logic.subscriptions import MAX_TTL_MS, MCPEventSubscriptions

__all__ = [
    "MAX_TTL_MS",
    "get_subscription",
    "list_subscriptions",
    "preview",
    "subscribe",
    "unsubscribe",
    "validate_mcp_callback_url",
    "validate_mcp_signing_secret",
]


def _service(*, team_id: int, user_id: int, principal: str = "") -> MCPEventSubscriptions:
    return MCPEventSubscriptions(
        team=Team.objects.get(id=team_id), user=User.objects.get(id=user_id), principal=principal
    )


def validate_mcp_callback_url(url: str) -> str:
    return validate_callback_url(url)


def validate_mcp_signing_secret(secret: str) -> str:
    signing_key(secret)
    return secret


def list_subscriptions(*, team_id: int, user_id: int, limit: int, offset: int) -> contracts.MCPEventSubscriptionPage:
    return _service(team_id=team_id, user_id=user_id).list_subscriptions(limit=limit, offset=offset)


def get_subscription(*, team_id: int, user_id: int, subscription_id: UUID) -> contracts.MCPEventSubscriptionRecord:
    record = _service(team_id=team_id, user_id=user_id).get(subscription_id)
    if record is None:
        raise contracts.MCPEventSubscriptionNotFoundError
    return record


def preview(*, team_id: int, user_id: int, filters: dict[str, JsonValue]) -> contracts.MCPEventPreview:
    return _service(team_id=team_id, user_id=user_id).preview(filters)


def subscribe(request: contracts.MCPEventSubscribeInput) -> contracts.MCPEventSubscriptionRecord:
    return _service(team_id=request.team_id, user_id=request.user_id, principal=request.principal).subscribe(
        raw_filters=request.filters,
        url=request.url,
        secret=request.secret,
        ttl_ms=request.ttl_ms,
        credential_expires_at=request.credential_expires_at,
    )


def unsubscribe(*, team_id: int, user_id: int, principal: str, filters: dict[str, JsonValue], url: str) -> None:
    _service(team_id=team_id, user_id=user_id, principal=principal).unsubscribe(raw_filters=filters, url=url)
