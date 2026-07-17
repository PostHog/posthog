from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class CursorEndpointConfig:
    name: str
    path: str
    method: Literal["GET", "POST"] = "POST"
    data_key: str = "data"  # Response key holding the list of rows
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Endpoint takes startDate/endDate epoch-ms body params with a 30-day max range,
    # so syncs chunk the requested range into windows.
    windowed: bool = False
    paginated: bool = True
    page_size: int = 100
    partition_key: Optional[str] = None  # Stable datetime field to partition by
    description: Optional[str] = None
    should_sync_default: bool = True


CURSOR_ENDPOINTS: dict[str, CursorEndpointConfig] = {
    "members": CursorEndpointConfig(
        name="members",
        path="/teams/members",
        method="GET",
        data_key="teamMembers",
        primary_keys=["id"],
        paginated=False,
        description="Current team members with their roles. Full refresh only",
    ),
    "daily_usage": CursorEndpointConfig(
        name="daily_usage",
        path="/teams/daily-usage-data",
        data_key="data",
        # One row per team member per day.
        primary_keys=["date", "userId"],
        windowed=True,
        partition_key="date",
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.DateTime,
                "field": "date",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        description="Per-user daily usage metrics (lines accepted, tabs, agent requests). Only syncs the last 365 days on initial sync",
    ),
    "usage_events": CursorEndpointConfig(
        name="usage_events",
        path="/teams/filtered-usage-events",
        data_key="usageEvents",
        # The API returns no event identifier, so `id` is synthesized in cursor.py from a
        # hash of the raw event payload — identical payloads dedupe, distinct ones never collide.
        primary_keys=["id"],
        windowed=True,
        partition_key="timestamp",
        incremental_fields=[
            {
                "label": "timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "timestamp",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        description="Per-request usage events with model, token usage, and cost. Only syncs the last 365 days on initial sync",
    ),
    "spend": CursorEndpointConfig(
        name="spend",
        path="/teams/spend",
        data_key="teamMemberSpend",
        primary_keys=["userId"],
        description="Per-member spend for the current billing cycle. Full refresh only",
    ),
}

ENDPOINTS = tuple(CURSOR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CURSOR_ENDPOINTS.items()
}
