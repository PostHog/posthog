from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class AnthropicEndpointConfig:
    name: str
    path: str
    # "entity" = after_id-cursor list endpoint; "workspace_members" = per-workspace fan-out of
    # an entity list; "report" = time-bucketed usage/cost report paginated with a `page` token.
    kind: Literal["entity", "workspace_members", "report"]
    primary_keys: list[str]
    # Static extra query params sent on every request.
    params: dict[str, str] = field(default_factory=dict)
    # Report endpoints: dimensions requested via `group_by[]`.
    group_by: list[str] = field(default_factory=list)
    # Report endpoints: result fields that, together with the bucket start, uniquely identify a
    # row. Used to build the synthetic `id` primary key.
    key_fields: list[str] = field(default_factory=list)
    # Usage report accepts 1m/1h/1d; cost report is daily-only and rejects other widths, so it
    # sends no bucket_width at all.
    bucket_width: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Report buckets never move once
    # written, so the bucket start is safe.
    partition_key: Optional[str] = None


_BUCKET_STARTING_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "bucket_starting_at",
        "type": IncrementalFieldType.DateTime,
        "field": "bucket_starting_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]

ANTHROPIC_ENDPOINTS: dict[str, AnthropicEndpointConfig] = {
    "users": AnthropicEndpointConfig(
        name="users",
        path="/v1/organizations/users",
        kind="entity",
        primary_keys=["id"],
    ),
    "invites": AnthropicEndpointConfig(
        name="invites",
        path="/v1/organizations/invites",
        kind="entity",
        primary_keys=["id"],
    ),
    "workspaces": AnthropicEndpointConfig(
        name="workspaces",
        path="/v1/organizations/workspaces",
        kind="entity",
        primary_keys=["id"],
        params={"include_archived": "true"},
    ),
    "workspace_members": AnthropicEndpointConfig(
        name="workspace_members",
        path="/v1/organizations/workspaces/{workspace_id}/members",
        kind="workspace_members",
        # No id field on the API object; user_id is only unique within a workspace.
        primary_keys=["workspace_id", "user_id"],
    ),
    "api_keys": AnthropicEndpointConfig(
        name="api_keys",
        path="/v1/organizations/api_keys",
        kind="entity",
        primary_keys=["id"],
    ),
    "usage_report": AnthropicEndpointConfig(
        name="usage_report",
        path="/v1/organizations/usage_report/messages",
        kind="report",
        primary_keys=["id"],
        group_by=["api_key_id", "workspace_id", "model", "service_tier", "context_window", "inference_geo"],
        key_fields=["api_key_id", "workspace_id", "model", "service_tier", "context_window", "inference_geo"],
        bucket_width="1d",
        incremental_fields=_BUCKET_STARTING_AT_INCREMENTAL,
        partition_key="bucket_starting_at",
    ),
    "cost_report": AnthropicEndpointConfig(
        name="cost_report",
        path="/v1/organizations/cost_report",
        kind="report",
        primary_keys=["id"],
        group_by=["workspace_id", "description"],
        # Grouping by description populates the cost breakdown fields (cost_type, model,
        # token_type, ...), and one description can span several of those combinations, so they
        # all take part in the synthetic key.
        key_fields=[
            "workspace_id",
            "description",
            "cost_type",
            "model",
            "service_tier",
            "token_type",
            "context_window",
            "inference_geo",
            "currency",
        ],
        incremental_fields=_BUCKET_STARTING_AT_INCREMENTAL,
        partition_key="bucket_starting_at",
    ),
}

ENDPOINTS = tuple(ANTHROPIC_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ANTHROPIC_ENDPOINTS.items() if config.incremental_fields
}
