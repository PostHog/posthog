from dataclasses import dataclass, field
from typing import Optional

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


@dataclass
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

# A fan-out child accumulates one row per parent row per sync under append, so these tables offer
# incremental merge only.
MERGE_ONLY = tuple(name for name, config in CALLRAIL_ENDPOINTS.items() if config.fanout is not None)
