from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class GongEndpointConfig:
    name: str
    path: str
    # Key under which the records array lives in the JSON response (e.g. "calls", "users").
    response_key: str
    primary_key: str
    # Stable datetime field to partition by (never `updated`/`lastModified`). None disables partitioning.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only `True` when Gong exposes a genuine server-side timestamp filter for the endpoint.
    supports_incremental: bool = False
    # `/v2/calls` requires `fromDateTime` and caps each request to a 90-day range, so it is
    # synced by iterating bounded date windows rather than a single cursor scan.
    uses_date_window: bool = False


GONG_ENDPOINTS: dict[str, GongEndpointConfig] = {
    "calls": GongEndpointConfig(
        name="calls",
        path="/v2/calls",
        response_key="calls",
        primary_key="id",
        partition_key="started",
        supports_incremental=True,
        uses_date_window=True,
        incremental_fields=[
            {
                "label": "started",
                "type": IncrementalFieldType.DateTime,
                "field": "started",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "users": GongEndpointConfig(
        name="users",
        path="/v2/users",
        response_key="users",
        primary_key="id",
        partition_key="created",
    ),
    "scorecards": GongEndpointConfig(
        name="scorecards",
        path="/v2/settings/scorecards",
        response_key="scorecards",
        primary_key="scorecardId",
        partition_key="created",
    ),
    "workspaces": GongEndpointConfig(
        name="workspaces",
        path="/v2/workspaces",
        response_key="workspaces",
        primary_key="id",
    ),
}

ENDPOINTS = tuple(GONG_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GONG_ENDPOINTS.items()
}
