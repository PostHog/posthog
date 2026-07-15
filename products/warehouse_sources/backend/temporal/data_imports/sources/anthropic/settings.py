from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class PaginationType(Enum):
    # Entity list endpoints (users, workspaces, api_keys, ...) page with after_id/before_id cursors
    # and signal continuation via has_more + last_id.
    CURSOR = "cursor"
    # The usage_report/cost_report endpoints page with an opaque `page` token echoed back as
    # `next_page`, alongside has_more.
    PAGE = "page"


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class AnthropicEndpointConfig:
    name: str
    path: str
    pagination: PaginationType
    primary_keys: list[str]
    # Stable creation-style timestamp used for datetime partitioning. Never an `updated_at`-style
    # field (Anthropic entities don't expose one anyway).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # `supports_incremental` is only ever True where the API exposes a genuine server-side time
    # filter (the report endpoints via `starting_at`). Entity lists have no updated-since filter, so
    # they are full-refresh only.
    supports_incremental: bool = False
    # Report buckets get restated as late usage lands, so append would materialize duplicate rows;
    # they are merge-only. Entity lists are full refresh (no append either).
    supports_append: bool = False
    # Report-only: bucket granularity and the dimensions we group each bucket by.
    bucket_width: Optional[str] = None
    group_by: list[str] = field(default_factory=list)
    limit: Optional[int] = None
    # Re-read window (seconds) applied to the incremental watermark by the pipeline before it reaches
    # the source, so each run re-pulls recently-restated buckets. Merge dedupes them on the primary key.
    default_incremental_lookback_seconds: Optional[int] = None
    # workspace_members has no org-wide list endpoint; it fans out one request per workspace.
    fan_out_over_workspaces: bool = False
    # Extra static query params merged into every request (e.g. include_archived on workspaces).
    extra_params: dict[str, str] = field(default_factory=dict)
    should_sync_default: bool = True


# The report endpoints support every group_by the API documents. Requesting the full set gives the
# richest breakdown; unused dimensions come back null and the row's synthesized `id` still stays
# unique across the group_by combination.
_USAGE_GROUP_BY = [
    "account_id",
    "api_key_id",
    "service_account_id",
    "workspace_id",
    "model",
    "service_tier",
    "context_window",
    "inference_geo",
]
_COST_GROUP_BY = ["workspace_id", "description"]

# One day of restated buckets is re-pulled on every incremental run. Anthropic notes usage/cost data
# lands a few minutes after requests complete and a day's bucket keeps accumulating until it closes,
# so a trailing day covers late arrivals; merge dedupes the overlap on the synthesized `id`.
_REPORT_LOOKBACK_SECONDS = 60 * 60 * 24

ANTHROPIC_ENDPOINTS: dict[str, AnthropicEndpointConfig] = {
    "users": AnthropicEndpointConfig(
        name="users",
        path="/v1/organizations/users",
        pagination=PaginationType.CURSOR,
        primary_keys=["id"],
        partition_key="added_at",
    ),
    "invites": AnthropicEndpointConfig(
        name="invites",
        path="/v1/organizations/invites",
        pagination=PaginationType.CURSOR,
        primary_keys=["id"],
        partition_key="invited_at",
    ),
    "workspaces": AnthropicEndpointConfig(
        name="workspaces",
        path="/v1/organizations/workspaces",
        pagination=PaginationType.CURSOR,
        primary_keys=["id"],
        partition_key="created_at",
        # Include archived workspaces so the dimension table stays complete (archived workspaces are
        # still referenced by historical usage/cost rows).
        extra_params={"include_archived": "true"},
    ),
    "api_keys": AnthropicEndpointConfig(
        name="api_keys",
        path="/v1/organizations/api_keys",
        pagination=PaginationType.CURSOR,
        primary_keys=["id"],
        partition_key="created_at",
    ),
    # No org-wide member list exists; fan out over every workspace's /members endpoint. The key must
    # carry the workspace id since one user can be a member of many workspaces.
    "workspace_members": AnthropicEndpointConfig(
        name="workspace_members",
        path="/v1/organizations/workspaces/{workspace_id}/members",
        pagination=PaginationType.CURSOR,
        primary_keys=["workspace_id", "user_id"],
        fan_out_over_workspaces=True,
    ),
    "usage_report": AnthropicEndpointConfig(
        name="usage_report",
        path="/v1/organizations/usage_report/messages",
        pagination=PaginationType.PAGE,
        # `id` is synthesized from the bucket start + every group_by dimension (see anthropic.py):
        # a non-null, stable key so merge updates a bucket in place as its metrics get restated.
        primary_keys=["id"],
        partition_key="starting_at",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("starting_at")],
        bucket_width="1d",
        group_by=_USAGE_GROUP_BY,
        # Grouping by every dimension multiplies the result rows per bucket, so requesting the
        # 31-bucket max overflows the report's per-response result cap and the API 400s. The API
        # default keeps each page small; pagination still walks all history via `next_page`.
        limit=7,
        default_incremental_lookback_seconds=_REPORT_LOOKBACK_SECONDS,
    ),
    "cost_report": AnthropicEndpointConfig(
        name="cost_report",
        path="/v1/organizations/cost_report",
        pagination=PaginationType.PAGE,
        primary_keys=["id"],
        partition_key="starting_at",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("starting_at")],
        bucket_width="1d",  # cost report only supports daily granularity
        group_by=_COST_GROUP_BY,
        default_incremental_lookback_seconds=_REPORT_LOOKBACK_SECONDS,
    ),
}

ENDPOINTS = tuple(ANTHROPIC_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ANTHROPIC_ENDPOINTS.items()
}
