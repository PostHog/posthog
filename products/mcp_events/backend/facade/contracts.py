"""Contract types for mcp_events. No Django imports."""

from dataclasses import field
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import JsonValue
from pydantic.dataclasses import dataclass

MCP_EVENT_NAME: Literal["posthog.event_captured"] = "posthog.event_captured"


@dataclass(frozen=True)
class MCPEventSubscriptionRecord:
    id: UUID
    arguments: dict[str, JsonValue]
    callback_host: str
    expires_at: datetime
    active: bool
    created_at: datetime


@dataclass(frozen=True)
class MCPEventSubscriptionPage:
    count: int
    results: list[MCPEventSubscriptionRecord]


@dataclass(frozen=True)
class MCPEventData:
    event: str
    distinct_id: str
    properties: dict[str, JsonValue]


@dataclass(frozen=True)
class MCPEventEnvelope:
    eventId: str
    name: Literal["posthog.event_captured"]
    timestamp: datetime
    data: MCPEventData
    cursor: None


@dataclass(frozen=True)
class MCPEventPreview:
    filters: dict[str, JsonValue]
    examples: list[MCPEventEnvelope]
    lookback_days: int
    sample_limit: int


@dataclass(frozen=True)
class MCPEventCredential:
    principal: str
    id: str
    last_rolled_at: datetime | None = None


@dataclass(frozen=True)
class MCPEventSubscribeInput:
    team_id: int
    user_id: int
    credential: MCPEventCredential
    filters: dict[str, JsonValue]
    url: str
    secret: str = field(repr=False)
    ttl_ms: int | None


class MCPCallbackError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Callback verification failed. Check the receiving endpoint and try again.")


class MCPEventSubscriptionNotFoundError(Exception):
    pass
