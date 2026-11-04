"""Connect tokens hand the integration a user saves on the destination connect page back to the agent.

The agent gets a token with the connect link. The page reports the saved integration against the token,
and the agent reads the result with the token. Credentials never pass through the agent.
"""

import secrets
import dataclasses
from datetime import datetime, timedelta
from typing import Any

from django.core.cache import caches
from django.db import models
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager, IntegrationNotFound

CONNECT_TOKEN_TTL = timedelta(hours=1)
_CACHE_KEY_PREFIX = "wh_dest_connect"
# Pinned to the Redis writer: the agent polls a token right after it is issued, and a replica can lag.
_CACHE_ALIAS = "warehouse_destination_connect"


class DestinationConnectStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONNECTED = "connected", "Connected"
    EXPIRED = "expired", "Expired"


@frozen
class DestinationConnectToken:
    token: str = dataclasses.field(repr=False)
    team_id: int
    user_id: int
    integration_kind: str
    expires_at: datetime
    integration_id: int | None = None
    display_name: str | None = None

    def status(self, now: datetime) -> DestinationConnectStatus:
        if self.integration_id is not None:
            return DestinationConnectStatus.CONNECTED
        if now >= self.expires_at:
            return DestinationConnectStatus.EXPIRED
        return DestinationConnectStatus.PENDING


class ConnectTokenNotFound(LookupError):
    """The token is unknown, expired, or belongs to another project."""


class ConnectTokenOtherUser(PermissionError):
    """The token was issued to another user."""


class ConnectTokenInvalidIntegration(ValueError):
    """The integration cannot complete this token."""


def _cache_key(team_id: int, token: str) -> str:
    return f"{_CACHE_KEY_PREFIX}:{team_id}:{token}"


def _claim_key(team_id: int, token: str) -> str:
    return f"{_cache_key(team_id, token)}:claim"


def _save(record: DestinationConnectToken) -> None:
    payload: dict[str, Any] = dataclasses.asdict(record)
    payload["expires_at"] = record.expires_at.isoformat()
    caches[_CACHE_ALIAS].set(
        _cache_key(record.team_id, record.token), payload, timeout=int(CONNECT_TOKEN_TTL.total_seconds())
    )


def _load(team_id: int, token: str) -> DestinationConnectToken | None:
    payload = caches[_CACHE_ALIAS].get(_cache_key(team_id, token))
    if not isinstance(payload, dict):
        return None
    return DestinationConnectToken(**{**payload, "expires_at": datetime.fromisoformat(payload["expires_at"])})


def issue_connect_token(*, team_id: int, user_id: int, integration_kind: str) -> DestinationConnectToken:
    record = DestinationConnectToken(
        token=secrets.token_urlsafe(32),
        team_id=team_id,
        user_id=user_id,
        integration_kind=integration_kind,
        expires_at=timezone.now() + CONNECT_TOKEN_TTL,
    )
    _save(record)
    return record


def complete_connect_token(*, team_id: int, user_id: int, token: str, integration_id: int) -> DestinationConnectToken:
    record = _load(team_id, token)
    if record is None:
        raise ConnectTokenNotFound()
    if record.user_id != user_id:
        raise ConnectTokenOtherUser()
    if record.integration_id == integration_id:
        return record
    if record.integration_id is not None:
        raise ConnectTokenInvalidIntegration(
            "This link already reported another connection. Ask the assistant for a new link."
        )
    if record.status(timezone.now()) == DestinationConnectStatus.EXPIRED:
        raise ConnectTokenNotFound()

    try:
        integration = IntegrationManager.any.get(team_id, integration_id)
    except IntegrationNotFound:
        raise ConnectTokenInvalidIntegration("This connection does not exist in this project.")
    if integration.kind != record.integration_kind:
        raise ConnectTokenInvalidIntegration(
            f"This link needs a '{record.integration_kind}' connection, not '{integration.kind}'."
        )

    # Two tabs can complete the same pending token at once. The first claim wins, so the token never
    # switches integrations and the losing request fails like any other switch.
    if not caches[_CACHE_ALIAS].add(
        _claim_key(team_id, token), integration.id, timeout=int(CONNECT_TOKEN_TTL.total_seconds())
    ):
        if caches[_CACHE_ALIAS].get(_claim_key(team_id, token)) != integration.id:
            raise ConnectTokenInvalidIntegration(
                "This link already reported another connection. Ask the assistant for a new link."
            )

    completed = dataclasses.replace(record, integration_id=integration.id, display_name=integration.display_name)
    # Saving resets the cache timeout, so the agent can read the result for a full TTL after the user saves.
    _save(completed)
    return completed


def read_connect_token(*, team_id: int, user_id: int, token: str) -> DestinationConnectToken | None:
    """The token's record, or None when it is unknown, gone from the cache, or another user's."""
    record = _load(team_id, token)
    if record is None or record.user_id != user_id:
        return None
    return record
