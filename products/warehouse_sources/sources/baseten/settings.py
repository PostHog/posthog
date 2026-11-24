import datetime
from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

# Baseten's management API returns full arrays for its entity list endpoints (no server-side
# `updated_since` filter on any of them), so those tables sync as a full refresh. A few endpoints
# (users, model_apis, audit_logs) use cursor+limit pagination; the rest are single unpaginated
# requests, and a few are fan-out children fetched once per parent resource. audit_logs alone has a
# server-side time filter (`start_epoch_millis`), so it alone syncs incrementally.

# The usage summary rejects ranges that start before this date.
BILLING_USAGE_EARLIEST_DATE = datetime.date(2026, 1, 1)
# The usage summary caps a range at 31 days.
BILLING_USAGE_WINDOW_DAYS = 30


@dataclass(frozen=True)
class BasetenEndpointConfig:
    name: str
    # Path template. For fan-out children it carries a `{<fan_out_path_param>}` placeholder that is
    # substituted with the parent field value per parent row.
    path: str
    # Key in the JSON response body holding the row array (e.g. {"models": [...]}). Cursor endpoints
    # return {"items": [...], "pagination": {...}}.
    data_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # STABLE creation timestamp used for datetime partitioning. None for endpoints whose rows have no
    # stable creation timestamp (reference tables, cursor-paginated user/model_api catalogs).
    partition_key: Optional[str] = None
    # True for endpoints that page via cursor+limit, returning a `pagination` object.
    paginated: bool = False
    # Credits apply only per usage type and window, so "usage_totals" keeps that grain next to the
    # daily rows of "usage_daily".
    mode: Literal["list", "usage_daily", "usage_totals"] = "list"
    params: dict[str, str] = field(default_factory=dict)
    # Field the server can filter on, in epoch milliseconds, for incremental syncs.
    incremental_field: Optional[str] = None
    # Fan-out: iterate the named parent endpoint and call this child once per parent row.
    fan_out_parent: Optional[str] = None
    fan_out_path_param: str = "parent_id"  # placeholder name in `path`
    fan_out_parent_field: str = "id"  # field read off the parent row to fill the placeholder
    # Parent field -> child column: copies parent context onto each child row so the linkage column
    # is always present (and the composite primary key stays unique table-wide).
    fan_out_include_parent_fields: Optional[dict[str, str]] = None
    # Flatten a nested object in each row up into the root (instance_type_prices wraps the instance
    # type under `instance_type` alongside a sibling `price`).
    flatten_key: Optional[str] = None
    should_sync_default: bool = True


BASETEN_ENDPOINTS: dict[str, BasetenEndpointConfig] = {
    "models": BasetenEndpointConfig(
        name="models",
        path="/v1/models",
        data_key="models",
        partition_key="created_at",
    ),
    "deployments": BasetenEndpointConfig(
        name="deployments",
        path="/v1/models/{model_id}/deployments",
        data_key="deployments",
        partition_key="created_at",
        fan_out_parent="models",
        fan_out_path_param="model_id",
        fan_out_include_parent_fields={"id": "model_id"},
    ),
    "model_environments": BasetenEndpointConfig(
        name="model_environments",
        path="/v1/models/{model_id}/environments",
        data_key="environments",
        # Environment names ("production", "staging", ...) repeat across models, so the name is only
        # unique within its model — key on both to stay unique table-wide.
        primary_keys=["model_id", "name"],
        partition_key="created_at",
        fan_out_parent="models",
        fan_out_path_param="model_id",
        fan_out_include_parent_fields={"id": "model_id"},
    ),
    "chains": BasetenEndpointConfig(
        name="chains",
        path="/v1/chains",
        data_key="chains",
        partition_key="created_at",
    ),
    "chain_deployments": BasetenEndpointConfig(
        name="chain_deployments",
        path="/v1/chains/{chain_id}/deployments",
        data_key="deployments",
        partition_key="created_at",
        fan_out_parent="chains",
        fan_out_path_param="chain_id",
        fan_out_include_parent_fields={"id": "chain_id"},
    ),
    "training_projects": BasetenEndpointConfig(
        name="training_projects",
        path="/v1/training_projects",
        data_key="training_projects",
        partition_key="created_at",
    ),
    "training_jobs": BasetenEndpointConfig(
        name="training_jobs",
        path="/v1/training_projects/{training_project_id}/jobs",
        data_key="training_jobs",
        partition_key="created_at",
        fan_out_parent="training_projects",
        fan_out_path_param="training_project_id",
        fan_out_include_parent_fields={"id": "training_project_id"},
    ),
    "users": BasetenEndpointConfig(
        name="users",
        path="/v1/users",
        data_key="items",
        primary_keys=["user_id"],
        paginated=True,
    ),
    "model_apis": BasetenEndpointConfig(
        name="model_apis",
        path="/v1/model_apis",
        data_key="items",
        primary_keys=["name"],
        paginated=True,
    ),
    "instance_types": BasetenEndpointConfig(
        name="instance_types",
        path="/v1/instance_types",
        data_key="instance_types",
    ),
    "instance_type_prices": BasetenEndpointConfig(
        name="instance_type_prices",
        path="/v1/instance_type_prices",
        data_key="instance_types",
        flatten_key="instance_type",
    ),
    "secrets": BasetenEndpointConfig(
        name="secrets",
        path="/v1/secrets",
        data_key="secrets",
        partition_key="created_at",
    ),
    "teams": BasetenEndpointConfig(
        name="teams",
        path="/v1/teams",
        data_key="teams",
        partition_key="created_at",
    ),
    "audit_logs": BasetenEndpointConfig(
        name="audit_logs",
        path="/v1/audit_logs",
        data_key="items",
        partition_key="created",
        paginated=True,
        params={"direction": "ASC"},
        incremental_field="created",
    ),
    "billing_usage": BasetenEndpointConfig(
        name="billing_usage",
        path="/v1/billing/usage_summary",
        data_key="",
        # The usage type keeps resource ids apart from the team and model names of Model API rows.
        primary_keys=["usage_type", "resource_id", "date"],
        partition_key="date",
        mode="usage_daily",
    ),
    "billing_usage_totals": BasetenEndpointConfig(
        name="billing_usage_totals",
        path="/v1/billing/usage_summary",
        data_key="",
        primary_keys=["usage_type", "window_start"],
        partition_key="window_start",
        mode="usage_totals",
    ),
}

ENDPOINTS = tuple(BASETEN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": config.incremental_field,
            "type": IncrementalFieldType.DateTime,
            "field": config.incremental_field,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for name, config in BASETEN_ENDPOINTS.items()
    if config.incremental_field
}
