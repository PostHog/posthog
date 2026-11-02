from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Max allowed by the API. Larger pages mean fewer requests against the per-account hourly/daily
# rate limits (1,000/hour and 10,000/day across the whole account).
PER_PAGE = 250

# A parent row deleted or merged between the parent listing and this child fetch answers 404;
# ignoring it keeps the fan-out going instead of failing the whole table. Page views also only
# exist for calls placed to a session tracker.
_CHILD_404_IGNORE: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]

_CALL_SUMMARY_FIELDS = (
    "total_calls,missed_calls,answered_calls,first_time_callers,average_duration,formatted_average_duration,leads"
)


@dataclass(frozen=True)
class CallRailEndpointConfig:
    name: str
    # Full path under https://api.callrail.com/v3, with `{account_id}` left for the resolved
    # account. Fan-out children also carry the parent's `{...}` placeholder, bound per parent row.
    path: str
    # Key the list lives under in the JSON envelope, e.g. {"calls": [...], "total_pages": N}.
    response_key: str
    incremental_fields: list[IncrementalField]
    # Stable datetime field used for datetime partitioning. Only set where we are confident the
    # field is present on every row (never `updated_at` / `last_*` — those rewrite partitions).
    partition_key: Optional[str] = None
    # Field passed to the API's `sort=` param (ascending) and, for incremental endpoints, the field
    # the `start_date` server-side filter narrows on. Required when supports_incremental is True so
    # rows arrive in ascending cursor order and the watermark advances correctly.
    sort_field: Optional[str] = None
    # True only where CallRail exposes a genuine server-side date filter (`start_date`) on this
    # resource. Everything else is full refresh.
    supports_incremental: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Set for endpoints reached once per parent row rather than once per account.
    fanout: Optional[DependentEndpointConfig] = None
    # Static query params, such as `fields=` for columns the API only returns on request.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Set for listings that fall back to CallRail's `recent` window (the last 7 days) when sent no
    # dates, so they get an explicit range that covers the retention period instead.
    retention_window: bool = False
    # Set for the vendor-computed report endpoints, which take one calendar-month date window per
    # request instead of pages. A "summary" report carries no date on its rows, so each row gets the
    # window it covers.
    report: Optional[Literal["timeseries", "summary"]] = None

    @property
    def requires_account(self) -> bool:
        return "{account_id}" in self.path

    @property
    def page_size(self) -> int:
        return PER_PAGE

    @property
    def default_incremental_field(self) -> Optional[str]:
        return self.incremental_fields[0]["field"] if self.incremental_fields else None


_PAGE_VIEWS_FANOUT = DependentEndpointConfig(
    parent_name="calls",
    resolve_param="call_id",
    resolve_field="id",
    # Page-view rows carry no id of their own, so the parent call id is both the only link back to
    # the call and part of the primary key.
    include_from_parent=["id"],
    parent_field_renames={"id": "call_id"},
    child_response_actions=_CHILD_404_IGNORE,
)

_CALLER_IDS_FANOUT = DependentEndpointConfig(
    parent_name="companies",
    resolve_param="company_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "company_id"},
    child_response_actions=_CHILD_404_IGNORE,
)

_LEAD_TIMELINE_FANOUT = DependentEndpointConfig(
    parent_name="leads",
    resolve_param="lead_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "lead_id"},
    child_response_actions=_CHILD_404_IGNORE,
)


# CallRail v3 REST API. Most data endpoints are nested under /v3/a/{account_id}/; the account
# listing itself sits at /v3/a.json.
#
# Incremental support is set only for resources whose list endpoint documents a server-side
# `start_date` date filter that narrows on a stable timestamp (Calls -> start_time,
# Form submissions -> submitted_at). For those we advertise exactly that one field as the
# incremental cursor so the cursor, the `sort=` field, and the `start_date` filter all agree.
# The report endpoints (calls and form summaries, calls timeseries) take the same date filter and
# advance on the date of the window they cover.
# The remaining resources are mutable configuration objects or lack a usable server-side date
# filter, so they ship full refresh only.
CALLRAIL_ENDPOINTS: dict[str, CallRailEndpointConfig] = {
    "accounts": CallRailEndpointConfig(
        name="accounts",
        path="/a.json",
        response_key="accounts",
        # Accounts carry no timestamp, so there is nothing to partition on. `name` is the only
        # sortable field, which is enough to keep pagination stable.
        sort_field="name",
        incremental_fields=[],
    ),
    "calls": CallRailEndpointConfig(
        name="calls",
        path="/a/{account_id}/calls.json",
        response_key="calls",
        partition_key="start_time",
        sort_field="start_time",
        supports_incremental=True,
        incremental_fields=[
            {
                "label": "start_time",
                "type": IncrementalFieldType.DateTime,
                "field": "start_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "calls_summary": CallRailEndpointConfig(
        name="calls_summary",
        path="/a/{account_id}/calls/summary.json",
        response_key="grouped_results",
        primary_keys=["period_start", "key"],
        supports_incremental=True,
        report="summary",
        extra_params={"group_by": "source", "fields": _CALL_SUMMARY_FIELDS},
        incremental_fields=[
            {
                "label": "period_start",
                "type": IncrementalFieldType.Date,
                "field": "period_start",
                "field_type": IncrementalFieldType.Date,
            },
        ],
    ),
    "calls_timeseries": CallRailEndpointConfig(
        name="calls_timeseries",
        path="/a/{account_id}/calls/timeseries.json",
        response_key="data",
        primary_keys=["date"],
        supports_incremental=True,
        report="timeseries",
        extra_params={"interval": "day", "fields": _CALL_SUMMARY_FIELDS},
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            },
        ],
    ),
    "companies": CallRailEndpointConfig(
        name="companies",
        path="/a/{account_id}/companies.json",
        response_key="companies",
        partition_key="created_at",
        incremental_fields=[],
    ),
    "form_submissions": CallRailEndpointConfig(
        name="form_submissions",
        path="/a/{account_id}/form_submissions.json",
        response_key="form_submissions",
        partition_key="submitted_at",
        sort_field="submitted_at",
        supports_incremental=True,
        incremental_fields=[
            {
                "label": "submitted_at",
                "type": IncrementalFieldType.DateTime,
                "field": "submitted_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "form_submissions_summary": CallRailEndpointConfig(
        name="form_submissions_summary",
        path="/a/{account_id}/forms/summary.json",
        response_key="grouped_results",
        primary_keys=["period_start", "key"],
        supports_incremental=True,
        report="summary",
        extra_params={"group_by": "source", "fields": "total_forms,first_forms,leads"},
        incremental_fields=[
            {
                "label": "period_start",
                "type": IncrementalFieldType.Date,
                "field": "period_start",
                "field_type": IncrementalFieldType.Date,
            },
        ],
    ),
    "leads": CallRailEndpointConfig(
        name="leads",
        path="/a/{account_id}/leads.json",
        response_key="leads",
        partition_key="created_at",
        # Sortable, but not filterable: CallRail's date filters cover calls, the call summary, and
        # conversations only, so leads is full refresh.
        sort_field="created_at",
        incremental_fields=[],
    ),
    "lead_timelines": CallRailEndpointConfig(
        name="lead_timelines",
        path="/a/{account_id}/leads/{lead_id}/timeline.json",
        # The envelope also carries a `lead` summary object; the timeline events are the row grain.
        response_key="timeline",
        partition_key="event_date",
        sort_field="event_date",
        # Timeline event ids are only documented as unique within their lead's timeline, and one
        # lead's history can mix a call, a form submission and a milestone, so the key spans all
        # three parts.
        primary_keys=["lead_id", "type", "id"],
        fanout=_LEAD_TIMELINE_FANOUT,
        # One request per lead against a 1,000/hour account-wide budget, so leave it to the user
        # to opt in rather than enabling it on every new connection.
        should_sync_default=False,
        # `supports_incremental` stays false: the endpoint takes no date filter, so the request set
        # is bounded by the parent listing. The cursor exists so the table merges on its primary key
        # instead of being replaced, which keeps the events that fall outside a run's parent window.
        incremental_fields=[
            {
                "label": "event_date",
                "type": IncrementalFieldType.DateTime,
                "field": "event_date",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "outbound_caller_ids": CallRailEndpointConfig(
        name="outbound_caller_ids",
        # `company_id` is a required query param, bound per company row by the fan-out.
        path="/a/{account_id}/caller_ids.json?company_id={company_id}",
        response_key="caller_ids",
        partition_key="created_at",
        primary_keys=["company_id", "id"],
        fanout=_CALLER_IDS_FANOUT,
        # One request per company against a 1,000/hour account-wide budget, so leave it to the user
        # to opt in rather than enabling it on every new connection.
        should_sync_default=False,
        # The parent companies listing is not windowed, so a full refresh sees every caller ID.
        incremental_fields=[],
    ),
    "page_views": CallRailEndpointConfig(
        name="page_views",
        path="/a/{account_id}/calls/{call_id}/page_views.json",
        response_key="page_views",
        partition_key="created_at",
        # Page-view rows have no id of their own. This is the most selective key the response
        # offers; two views of the same page within the same second would collapse into one row.
        primary_keys=["call_id", "created_at", "page_url"],
        fanout=_PAGE_VIEWS_FANOUT,
        # One request per call against a 1,000/hour account-wide budget, so leave it to the user
        # to opt in rather than enabling it on every new connection.
        should_sync_default=False,
        # Same as lead_timelines: no date filter on the endpoint, so the cursor only buys a merge.
        # It matters more here because the parent calls listing defaults to CallRail's `recent`
        # window (the last 7 days), so a replace would leave the table holding only that week.
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "sms_threads": CallRailEndpointConfig(
        name="sms_threads",
        path="/a/{account_id}/sms-threads.json",
        response_key="sms_threads",
        # The listing takes no sort param and returns the thread with the newest message first. Its
        # date filter is not documented as narrowing on a stable field, so this is full refresh.
        retention_window=True,
        extra_params={"fields": "last_message_at"},
        incremental_fields=[],
    ),
    "text_messages": CallRailEndpointConfig(
        name="text_messages",
        # Returns SMS conversations under the "conversations" key.
        path="/a/{account_id}/text-messages.json",
        response_key="conversations",
        incremental_fields=[],
    ),
    "trackers": CallRailEndpointConfig(
        name="trackers",
        path="/a/{account_id}/trackers.json",
        response_key="trackers",
        incremental_fields=[],
    ),
    "users": CallRailEndpointConfig(
        name="users",
        path="/a/{account_id}/users.json",
        response_key="users",
        incremental_fields=[],
    ),
    "tags": CallRailEndpointConfig(
        name="tags",
        path="/a/{account_id}/tags.json",
        response_key="tags",
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(CALLRAIL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CALLRAIL_ENDPOINTS.items()
}

SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: config.should_sync_default for name, config in CALLRAIL_ENDPOINTS.items()}

# A fan-out child accumulates one row per parent row per sync under append, and a report re-reads
# the current month on every sync, so these tables offer incremental merge only.
MERGE_ONLY = tuple(
    name for name, config in CALLRAIL_ENDPOINTS.items() if config.fanout is not None or config.report is not None
)
