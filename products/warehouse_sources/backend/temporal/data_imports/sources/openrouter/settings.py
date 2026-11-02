from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# The /activity rollups only cover the last 30 completed UTC days; older data isn't retrievable
# through this endpoint, so both the first sync and every incremental sync are bounded to this window.
ACTIVITY_RETENTION_DAYS = 30

PaginationMode = Literal["offset", "offset_limit", "cursor"]


@dataclass(frozen=True)
class OpenRouterEndpointConfig:
    name: str
    path: str
    # Management endpoints (activity/api_keys/credits/organization_members/workspaces) require an
    # OpenRouter management key; the models/providers catalogs are public and read with any valid key.
    requires_management_key: bool
    # Batches are scoped to the workspace of the calling key, which an account-level management key
    # doesn't have, so they can only be read with a regular inference key.
    requires_inference_key: bool = False
    # Table-wide unique key. None for the /credits singleton (a single balance snapshot, full-refresh
    # replace, so there's nothing to merge on).
    primary_keys: Optional[list[str]] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime field to partition by (never a mutable field like updated_at).
    partition_key: Optional[str] = None
    # Offset-based pagination style, or None for a single unpaginated request.
    #   "offset"       -> only an `offset` query param (e.g. /keys)
    #   "offset_limit" -> `offset` + `limit` query params (e.g. /organization/members, /workspaces)
    #   "cursor"       -> `after` set to the previous page's `last_id` while `has_more` (e.g. /batches)
    pagination: Optional[PaginationMode] = None
    page_size: int = 100
    # Fixed query params sent on every page.
    params: dict[str, str] = field(default_factory=dict)
    sort_mode: Literal["asc", "desc"] = "asc"
    # `data` is a single object rather than a list of rows (e.g. /credits).
    is_singleton: bool = False
    # Day-by-day pull driven by the ?date= filter (only /activity). See openrouter.py.
    daily_activity: bool = False
    # Fan-out child: `path` holds a `{parent_id}` placeholder filled with each `id` of this parent
    # endpoint, and `pagination` applies to the child requests.
    fan_out_parent: Optional[str] = None
    # Child response `data` is an object holding the rows under this key (e.g. a model's endpoints).
    child_rows_key: Optional[str] = None
    # Column the parent id is copied into, for child rows that don't carry it themselves.
    parent_id_column: Optional[str] = None
    # /classifications/task wraps its rows with the snapshot date and window. See openrouter.py.
    task_classifications: bool = False
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
    "end_users": OpenRouterEndpointConfig(
        name="end_users",
        path="/end-users",
        requires_management_key=True,
        primary_keys=["user"],
        partition_key="created_at",
        pagination="offset_limit",
        # Deactivated registrations are hidden by default; include them so a full refresh keeps their
        # rows with is_active=false instead of dropping them.
        params={"include_inactive": "true"},
    ),
    "workspace_members": OpenRouterEndpointConfig(
        name="workspace_members",
        path="/workspaces/{parent_id}/members",
        requires_management_key=True,
        # The default workspace lists every organization member through implicit membership, and the
        # docs don't say what `id` holds for those rows, so key on the workspace and user instead.
        primary_keys=["workspace_id", "user_id"],
        partition_key="created_at",
        pagination="offset_limit",
        fan_out_parent="workspaces",
    ),
    "model_endpoints": OpenRouterEndpointConfig(
        name="model_endpoints",
        path="/models/{parent_id}/endpoints",
        requires_management_key=False,
        # `model_id` is the permaslug, which variants such as `:free` share with their base model, so
        # the requested model id keys the rows. `tag` is unique per model, e.g. "azure/swedencentral".
        primary_keys=["parent_model_id", "tag"],
        fan_out_parent="models",
        child_rows_key="endpoints",
        parent_id_column="parent_model_id",
    ),
    "task_classifications": OpenRouterEndpointConfig(
        name="task_classifications",
        path="/classifications/task",
        requires_management_key=False,
        primary_keys=["tag"],
        # Only the trailing 7-day window exists today; pinned so a new default can't change the table.
        params={"window": "7d"},
        task_classifications=True,
    ),
    "batches": OpenRouterEndpointConfig(
        name="batches",
        path="/batches",
        requires_management_key=False,
        requires_inference_key=True,
        primary_keys=["id"],
        partition_key="created_at",
        pagination="cursor",
        # The list is newest-first only. Full refresh, because a batch's status, request counts and
        # usage keep changing after it's created.
        sort_mode="desc",
        # The source is usually connected with a management key, which can't read this table.
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(OPENROUTER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OPENROUTER_ENDPOINTS.items()
}
