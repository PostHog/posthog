from dataclasses import field
from datetime import date
from enum import Enum
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class PaginationType(Enum):
    # Entity list endpoints (users, workspaces, api_keys, ...) page with after_id/before_id cursors
    # and signal continuation via has_more + last_id.
    CURSOR = "cursor"
    # The usage_report/cost_report endpoints page with an opaque `page` token echoed back as
    # `next_page`, alongside has_more.
    PAGE = "page"


class AnalyticsWindowKind(Enum):
    # `/organizations/analytics/users` answers for one `date`.
    DATE = "date"
    # The per-user cost and token usage reports answer for a `starting_at`/`ending_at` range.
    RANGE = "range"


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@frozen
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
    # workspace_members has no org-wide list endpoint, so it fans out one request per workspace.
    fan_out_over_workspaces: bool = False
    # Claude Code analytics takes a single `starting_at` day per request, so it fans out one windowed
    # request per calendar day from the watermark (or launch floor) to today.
    fan_out_over_days: bool = False
    # Extra static query params merged into every request (e.g. include_archived on workspaces).
    extra_params: dict[str, str] = field(default_factory=dict)
    # The Claude Enterprise Analytics endpoints answer for one date (or one date range) per request,
    # so the source fans out one request per UTC day. Set to the window shape the endpoint takes.
    analytics_window: Optional[AnalyticsWindowKind] = None
    # Days by which the newest requestable day trails today. The engagement endpoints answer 400 for
    # a day their export has not covered yet, so their fan-out has to stop short of today.
    analytics_lag_days: int = 0
    # Oldest `starting_at` the endpoint accepts, in days before today. None means no such limit.
    analytics_max_history_days: Optional[int] = None
    should_sync_default: bool = True


# The usage report rejects a query whose `group_by` fans out further than it will serve, answering
# 400 for the whole request rather than a truncated page — and the ceiling is not documented, so it
# can't be picked up front. These are the group_by sets to try in order, richest first: the source
# drops to the next one when the API rejects the request, so a sync lands on the finest breakdown
# that org's report will actually serve instead of failing. Unused dimensions come back null and the
# row's synthesized `id` stays unique across whichever combination was accepted.
USAGE_GROUP_BY_FALLBACKS: list[list[str]] = [
    [
        "account_id",
        "api_key_id",
        "service_account_id",
        "workspace_id",
        "model",
        "service_tier",
        "context_window",
        "inference_geo",
    ],
    # Without the per-actor dimensions, which multiply out fastest.
    ["workspace_id", "model", "service_tier", "context_window", "inference_geo"],
    # The breakdown the cost report already serves at this bucket width.
    ["workspace_id", "model"],
    # Bucket totals only — the narrowest query the endpoint can be asked for.
    [],
]
_USAGE_GROUP_BY = USAGE_GROUP_BY_FALLBACKS[0]
_COST_GROUP_BY = ["workspace_id", "description"]

# Time buckets per cost report page, at the documented `1d` maximum. The report endpoints are the
# rate-limited part of this source — Anthropic supports polling them about once a minute for
# sustained use — and every page is one request, so walking history at the API's default of 7
# buckets spends more than four times the request budget for the same rows. The usage report keeps
# the smaller page: its rows are already multiplied out by `group_by`, so a wider window there buys
# fewer requests at the cost of a coarser breakdown.
COST_REPORT_PAGE_BUCKETS = 31
USAGE_REPORT_PAGE_BUCKETS = 7

# One day of restated buckets is re-pulled on every incremental run. Anthropic notes usage/cost data
# lands a few minutes after requests complete and a day's bucket keeps accumulating until it closes,
# so a trailing day covers late arrivals; merge dedupes the overlap on the synthesized `id`.
_REPORT_LOOKBACK_SECONDS = 60 * 60 * 24

# The Claude Enterprise Analytics API serves no data before this date, and answers 400 for an
# earlier one, so the day fan-out starts here on a full refresh.
ANALYTICS_DATA_FLOOR = date(2026, 1, 1)
# Rows per analytics page, at the documented maximum. Each page is one request against an
# organization-wide 60-requests-per-minute limit, so ask for as many rows per request as allowed.
ANALYTICS_PAGE_SIZE = 1000
# Engagement data for a day lands about a day later, and the most recent available day is often two
# days back. Requesting a day the export has not covered yet fails the whole request with a 400 that
# names the latest available day, so the engagement fan-out stops two days short of today.
ANALYTICS_ENGAGEMENT_LAG_DAYS = 2
# The per-user cost and usage reports reject a `starting_at` more than 365 days old. Stop a day
# inside that bound so a long-running full refresh cannot age past it mid-sync.
ANALYTICS_REPORT_MAX_HISTORY_DAYS = 364
# Engagement metrics for a day may be revised by a few percent over the following days, so re-pull a
# trailing window on every incremental run; merge dedupes the overlap on the synthesized `id`.
_ANALYTICS_ENGAGEMENT_LOOKBACK_SECONDS = 60 * 60 * 24 * 3
# Per-user cost and usage are refreshed about every four hours and stay open to revision for around
# 30 days as late events arrive and reconciliation runs. A week of re-pulled days keeps the recent
# tail accurate at a bounded request cost; run a full refresh for invoicing-grade totals.
_ANALYTICS_REPORT_LOOKBACK_SECONDS = 60 * 60 * 24 * 7

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
    # No service_accounts endpoint: Anthropic serves service accounts only to an org:admin OAuth
    # token and rejects the Admin API key this source authenticates with, so the table can never
    # sync. `service_account_id` still resolves as a usage_report group_by dimension below.
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
        limit=USAGE_REPORT_PAGE_BUCKETS,
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
        limit=COST_REPORT_PAGE_BUCKETS,
        default_incremental_lookback_seconds=_REPORT_LOOKBACK_SECONDS,
    ),
    # Claude Code analytics: one record per user per day. The endpoint windows on a single `starting_at`
    # day (page-cursored within the day), so the source fans out day by day. Split into two tables — the
    # per-day productivity metrics here, the per-model token/cost breakdown below — because those two
    # sit at different grains.
    "claude_code_analytics": AnthropicEndpointConfig(
        name="claude_code_analytics",
        path="/v1/organizations/usage_report/claude_code",
        pagination=PaginationType.PAGE,
        # `id` is synthesized from the day and every actor/terminal dimension (see anthropic.py).
        primary_keys=["id"],
        partition_key="date",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("date")],
        fan_out_over_days=True,
        limit=1000,
        # The current day keeps accruing (up to a 1-hour delay), so re-pull the trailing day; merge
        # dedupes the overlap on the synthesized `id`.
        default_incremental_lookback_seconds=_REPORT_LOOKBACK_SECONDS,
    ),
    "claude_code_model_breakdown": AnthropicEndpointConfig(
        name="claude_code_model_breakdown",
        path="/v1/organizations/usage_report/claude_code",
        pagination=PaginationType.PAGE,
        primary_keys=["id"],
        partition_key="date",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("date")],
        fan_out_over_days=True,
        limit=1000,
        default_incremental_lookback_seconds=_REPORT_LOOKBACK_SECONDS,
    ),
    # Claude Enterprise Analytics API: per-seat engagement, and cost and token usage attributed to a
    # seat user. These need a Claude Enterprise key carrying the `read:analytics` scope, which a
    # Claude Console Admin API key is not, so they stay off by default and `get_endpoint_permissions`
    # reports whether the configured key can reach them.
    "analytics_user_activity": AnthropicEndpointConfig(
        name="analytics_user_activity",
        path="/v1/organizations/analytics/users",
        pagination=PaginationType.PAGE,
        # `id` is synthesized from the requested day and the user id (see anthropic.py). The response
        # carries no day of its own, so the source stamps the day it asked for onto every row.
        primary_keys=["id"],
        partition_key="date",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("date")],
        analytics_window=AnalyticsWindowKind.DATE,
        analytics_lag_days=ANALYTICS_ENGAGEMENT_LAG_DAYS,
        limit=ANALYTICS_PAGE_SIZE,
        default_incremental_lookback_seconds=_ANALYTICS_ENGAGEMENT_LOOKBACK_SECONDS,
        should_sync_default=False,
    ),
    "analytics_user_cost": AnthropicEndpointConfig(
        name="analytics_user_cost",
        path="/v1/organizations/analytics/user_cost_report",
        pagination=PaginationType.PAGE,
        primary_keys=["id"],
        partition_key="starting_at",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("starting_at")],
        analytics_window=AnalyticsWindowKind.RANGE,
        analytics_max_history_days=ANALYTICS_REPORT_MAX_HISTORY_DAYS,
        # A row only carries its own `starting_at` when a bucket width is set. Without one the whole
        # requested range collapses into a single undated row per user, whose grain would then depend
        # on how wide a window the sync happened to ask for.
        bucket_width="1d",
        limit=ANALYTICS_PAGE_SIZE,
        default_incremental_lookback_seconds=_ANALYTICS_REPORT_LOOKBACK_SECONDS,
        should_sync_default=False,
    ),
    "analytics_user_usage": AnthropicEndpointConfig(
        name="analytics_user_usage",
        path="/v1/organizations/analytics/user_usage_report",
        pagination=PaginationType.PAGE,
        primary_keys=["id"],
        partition_key="starting_at",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("starting_at")],
        analytics_window=AnalyticsWindowKind.RANGE,
        analytics_max_history_days=ANALYTICS_REPORT_MAX_HISTORY_DAYS,
        bucket_width="1d",
        limit=ANALYTICS_PAGE_SIZE,
        default_incremental_lookback_seconds=_ANALYTICS_REPORT_LOOKBACK_SECONDS,
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(ANTHROPIC_ENDPOINTS.keys())

# Raised when a schema row names an endpoint the catalog no longer has, and matched by
# `get_non_retryable_errors` so the sync retires the row rather than retrying.
ENDPOINT_RETIRED_ERROR = "Table no longer available from Anthropic"

# Path prefix shared by every Claude Enterprise Analytics endpoint. A 403 from one of these means the
# key lacks the `read:analytics` scope rather than organization admin access, so the source maps it to
# its own message in `get_non_retryable_errors`.
ANALYTICS_PATH_PREFIX = "/v1/organizations/analytics/"

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ANTHROPIC_ENDPOINTS.items()
}
