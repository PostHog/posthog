from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# The /activity rollups only cover the last 30 completed UTC days; older data isn't retrievable
# through this endpoint, so both the first sync and every incremental sync are bounded to this window.
ACTIVITY_RETENTION_DAYS = 30

PaginationMode = Literal["offset", "offset_limit"]


@dataclass
class OpenRouterEndpointConfig:
    name: str
    path: str
    # Management endpoints (activity/api_keys/credits/organization_members/workspaces) require an
    # OpenRouter management key; the models/providers catalogs are public and read with any valid key.
    requires_management_key: bool
    # Table-wide unique key. None for the /credits singleton (a single balance snapshot, full-refresh
    # replace, so there's nothing to merge on).
    primary_keys: Optional[list[str]] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime field to partition by (never a mutable field like updated_at).
    partition_key: Optional[str] = None
    # Offset-based pagination style, or None for a single unpaginated request.
    #   "offset"       -> only an `offset` query param (e.g. /keys)
    #   "offset_limit" -> `offset` + `limit` query params (e.g. /organization/members, /workspaces)
    pagination: Optional[PaginationMode] = None
    page_size: int = 100
    # `data` is a single object rather than a list of rows (e.g. /credits).
    is_singleton: bool = False
    # Day-by-day pull driven by the ?date= filter (only /activity). See openrouter.py.
    daily_activity: bool = False
    should_sync_default: bool = True


# /activity is the only endpoint with a genuine server-side time filter (?date=<single UTC day>), so
# it's the only incremental table. Everything else is a small full-refresh table.
_ACTIVITY_DATE_FIELD: IncrementalField = {
    "label": "date",
    "type": IncrementalFieldType.Date,
    "field": "date",
    "field_type": IncrementalFieldType.Date,
}


OPENROUTER_ENDPOINTS: dict[str, OpenRouterEndpointConfig] = {
    "models": OpenRouterEndpointConfig(
        name="models",
        path="/models",
        requires_management_key=False,
        primary_keys=["id"],
    ),
    "providers": OpenRouterEndpointConfig(
        name="providers",
        path="/providers",
        requires_management_key=False,
        primary_keys=["slug"],
    ),
    "activity": OpenRouterEndpointConfig(
        name="activity",
        path="/activity",
        requires_management_key=True,
        # A row is one provider endpoint's usage for one UTC day; endpoint_id alone should be unique
        # per day, but the model/provider are included defensively so the key can't collide.
        primary_keys=["date", "endpoint_id", "model_permaslug", "provider_name"],
        partition_key="date",
        incremental_fields=[_ACTIVITY_DATE_FIELD],
        daily_activity=True,
    ),
    "api_keys": OpenRouterEndpointConfig(
        name="api_keys",
        path="/keys",
        requires_management_key=True,
        primary_keys=["hash"],
        pagination="offset",
    ),
    "credits": OpenRouterEndpointConfig(
        name="credits",
        path="/credits",
        requires_management_key=True,
        primary_keys=None,
        is_singleton=True,
    ),
    "organization_members": OpenRouterEndpointConfig(
        name="organization_members",
        path="/organization/members",
        requires_management_key=True,
        primary_keys=["id"],
        pagination="offset_limit",
    ),
    "workspaces": OpenRouterEndpointConfig(
        name="workspaces",
        path="/workspaces",
        requires_management_key=True,
        primary_keys=["id"],
        pagination="offset_limit",
    ),
}

ENDPOINTS = tuple(OPENROUTER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OPENROUTER_ENDPOINTS.items()
}
