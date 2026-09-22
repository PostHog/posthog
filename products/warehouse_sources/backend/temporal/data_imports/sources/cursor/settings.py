from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

MAX_WINDOW_DAYS = 30
# The Analytics API caps a range at 30 inclusive calendar days. Windows are millisecond ranges that
# are not midnight-aligned, so a 30-day window straddles 31 calendar dates once both ends are
# truncated to a date. 29 is the largest window that always fits.
ANALYTICS_MAX_WINDOW_DAYS = 29


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@frozen
class CursorEndpointConfig:
    name: str
    path: str
    method: Literal["GET", "POST"] = "POST"
    data_key: str = "data"  # Response key holding the list of rows
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Endpoint takes startDate/endDate params with a maximum range, so syncs chunk the requested
    # range into windows.
    windowed: bool = False
    window_days: int = MAX_WINDOW_DAYS
    # Analytics API endpoints take their params in the query string and their dates as YYYY-MM-DD;
    # the Admin API takes a JSON body with epoch-ms dates.
    query_params: bool = False
    date_param_format: Literal["epoch_ms", "iso_date"] = "epoch_ms"
    # Response `data` is an object keyed by user email instead of a list of rows.
    by_user: bool = False
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
        incremental_fields=[_datetime_field("date")],
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
        incremental_fields=[_datetime_field("timestamp")],
        description="Per-request usage events with model, token usage, and cost. Only syncs the last 365 days on initial sync",
    ),
    "spend": CursorEndpointConfig(
        name="spend",
        path="/teams/spend",
        data_key="teamMemberSpend",
        primary_keys=["userId"],
        description="Per-member spend for the current billing cycle. Full refresh only",
    ),
    "agent_edits": CursorEndpointConfig(
        name="agent_edits",
        path="/analytics/team/agent-edits",
        method="GET",
        query_params=True,
        date_param_format="iso_date",
        data_key="data",
        # One aggregate row per day for the whole team.
        primary_keys=["event_date"],
        windowed=True,
        window_days=ANALYTICS_MAX_WINDOW_DAYS,
        paginated=False,
        partition_key="event_date",
        incremental_fields=[_datetime_field("event_date")],
        should_sync_default=False,
        description="Daily team totals for agent-suggested edits: diffs suggested, accepted, and rejected, with line counts. Needs a Cursor Enterprise plan. Only syncs the last 365 days on initial sync",
    ),
    "tabs": CursorEndpointConfig(
        name="tabs",
        path="/analytics/team/tabs",
        method="GET",
        query_params=True,
        date_param_format="iso_date",
        data_key="data",
        primary_keys=["event_date"],
        windowed=True,
        window_days=ANALYTICS_MAX_WINDOW_DAYS,
        paginated=False,
        partition_key="event_date",
        incremental_fields=[_datetime_field("event_date")],
        should_sync_default=False,
        description="Daily team totals for Tab autocomplete: suggestions, accepts, rejects, and line counts. Needs a Cursor Enterprise plan. Only syncs the last 365 days on initial sync",
    ),
    "by_user_agent_edits": CursorEndpointConfig(
        name="by_user_agent_edits",
        path="/analytics/by-user/agent-edits",
        method="GET",
        query_params=True,
        date_param_format="iso_date",
        data_key="data",
        by_user=True,
        primary_keys=["event_date", "userEmail"],
        windowed=True,
        window_days=ANALYTICS_MAX_WINDOW_DAYS,
        page_size=500,
        partition_key="event_date",
        incremental_fields=[_datetime_field("event_date")],
        should_sync_default=False,
        description="Per-user daily agent edit metrics, keyed by email so they join to members. Needs a Cursor Enterprise plan. Only syncs the last 365 days on initial sync",
    ),
    "by_user_tabs": CursorEndpointConfig(
        name="by_user_tabs",
        path="/analytics/by-user/tabs",
        method="GET",
        query_params=True,
        date_param_format="iso_date",
        data_key="data",
        by_user=True,
        primary_keys=["event_date", "userEmail"],
        windowed=True,
        window_days=ANALYTICS_MAX_WINDOW_DAYS,
        page_size=500,
        partition_key="event_date",
        incremental_fields=[_datetime_field("event_date")],
        should_sync_default=False,
        description="Per-user daily Tab autocomplete metrics, keyed by email so they join to members. Needs a Cursor Enterprise plan. Only syncs the last 365 days on initial sync",
    ),
    "by_user_models": CursorEndpointConfig(
        name="by_user_models",
        path="/analytics/by-user/models",
        method="GET",
        query_params=True,
        date_param_format="iso_date",
        data_key="data",
        by_user=True,
        # One row per user per day per model, expanded from the per-model map the API returns.
        primary_keys=["date", "userEmail", "model"],
        windowed=True,
        window_days=ANALYTICS_MAX_WINDOW_DAYS,
        page_size=500,
        partition_key="date",
        incremental_fields=[_datetime_field("date")],
        should_sync_default=False,
        description="Per-user daily model usage, with a message count for each model. Needs a Cursor Enterprise plan. Only syncs the last 365 days on initial sync",
    ),
    "by_user_top_file_extensions": CursorEndpointConfig(
        name="by_user_top_file_extensions",
        path="/analytics/by-user/top-file-extensions",
        method="GET",
        query_params=True,
        date_param_format="iso_date",
        data_key="data",
        by_user=True,
        # One row per user per day per file extension.
        primary_keys=["event_date", "userEmail", "file_extension"],
        windowed=True,
        window_days=ANALYTICS_MAX_WINDOW_DAYS,
        page_size=500,
        partition_key="event_date",
        incremental_fields=[_datetime_field("event_date")],
        should_sync_default=False,
        description="Per-user daily file extension breakdown of AI-assisted edits. Needs a Cursor Enterprise plan. Only syncs the last 365 days on initial sync",
    ),
    "ai_code_commits": CursorEndpointConfig(
        name="ai_code_commits",
        path="/analytics/ai-code/commits",
        method="GET",
        query_params=True,
        date_param_format="iso_date",
        data_key="items",
        # A commit hash is unique per commit; the author is in the key too because the docs
        # scope uniqueness to the aggregate, not to the hash.
        primary_keys=["commitHash", "userId"],
        windowed=True,
        window_days=ANALYTICS_MAX_WINDOW_DAYS,
        page_size=1000,
        partition_key="commitTs",
        incremental_fields=[_datetime_field("commitTs")],
        should_sync_default=False,
        description="Per-commit attribution of lines added and deleted to Tab, Composer, and non-AI authoring. Needs a Cursor Enterprise plan with AI code tracking enabled. Only syncs the last 365 days on initial sync",
    ),
}

ENDPOINTS = tuple(CURSOR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CURSOR_ENDPOINTS.items()
}
