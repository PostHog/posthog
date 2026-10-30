from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How a list endpoint is walked:
# - "offset":   `limit`/`offset` query params over a bare JSON array (suppression endpoints).
# - "metadata": follow the absolute `_metadata.next` URL the API returns (marketing endpoints).
# - "single":   one request returns the whole list, no pagination params.
# - "activity": no cursor at all — the Email Activity `query` time window is narrowed newest to
#               oldest until a short page (message_activity).
PaginationMode = Literal["offset", "metadata", "single", "activity"]

# The Email Activity add-on stores 30 days of history, so a message_activity sync with no
# incremental cursor yet starts its query window this far back.
MESSAGE_ACTIVITY_BACKFILL_DAYS = 30

# How the incremental cursor is serialized into the `incremental_param` query value:
# - "epoch": Unix epoch seconds (suppression `start_time`).
# - "date":  `YYYY-MM-DD` (stats `start_date`).
IncrementalParamFormat = Literal["epoch", "date"]

# Shape of a 200 response body, so the transport knows whether it needs flattening:
# - "array":       the rows are the JSON body itself, or the array under `data_key`.
# - "daily_stats": nested `[{date, stats: [{metrics: {...}}]}]` that flattens to one row per
#                  metrics bucket with `date` merged in (the /stats family).
# - "category_stats": the same nesting, flattened to one row per date with the requested
#                  `category` merged in (category_stats).
ResponseShape = Literal["array", "daily_stats", "category_stats"]

# /stats requires `start_date` on every request, so the first sync (no cursor yet) backfills this
# far back. Daily aggregation means one row per day, so a year is cheap and gives enough history to
# compare deliverability trends.
STATS_DEFAULT_BACKFILL_DAYS = 365


@dataclass(frozen=False)
class SendGridEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    pagination: PaginationMode
    # Key wrapping the array in the JSON response (e.g. {"result": [...]}). None when the
    # response body is the array itself (the suppression endpoints).
    data_key: Optional[str] = None
    # Stable creation field used for datetime partitioning. Never use a "modified" field here.
    partition_key: Optional[str] = None
    page_size: int = 500
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Server-side query param that filters by the incremental field.
    incremental_param: Optional[str] = None
    # How the cursor value is written into `incremental_param`.
    incremental_param_format: IncrementalParamFormat = "epoch"
    # Number of days back to backfill when `incremental_param` is required by the API but there's no
    # cursor yet (first sync, or full refresh). None leaves the param off unless a cursor exists —
    # the right default for a genuinely optional filter like the suppression endpoints' `start_time`.
    default_backfill_days: Optional[int] = None
    # How the response body is shaped, so the transport can flatten nested stats responses.
    response_shape: ResponseShape = "array"
    # Order rows arrive in across the whole sync. The Email Activity walk pages newest to oldest,
    # so it declares "desc" and the pipeline defers the incremental watermark to the end of a
    # successful run instead of checkpointing it per batch. None when rows come one parent at a
    # time, so they form no single ordered series.
    sort_mode: Optional[Literal["asc", "desc"]] = "asc"
    # False for tables whose sync needs grants beyond what source creation validated: the schema
    # picker and one-shot source creation leave them unselected until the user opts in.
    should_sync_default: bool = True
    # Static query params always sent (e.g. templates' `generations`).
    extra_params: dict[str, str] = field(default_factory=dict)
    # SendGrid scope this endpoint reads, spelled as `/scopes` reports it. Surfaced per table in the
    # schema picker when the key can't reach the endpoint, so the user grants that one access rather
    # than regenerating a key that was never the problem.
    required_scope: str = ""
    # Appended to the missing-scope message where granting the scope may not be enough on its own.
    permission_note: Optional[str] = None
    # Structural requirement of `FanoutEndpointLike` (see common/rest_source/fanout.py).
    default_incremental_field: Optional[str] = None
    # Set on a child endpoint whose path takes one id per row of a parent endpoint.
    fanout: Optional[DependentEndpointConfig] = None
    # Placeholder parent value to probe the child path with, for a fan-out child that reads with a
    # different scope than its parent. None probes the parent listing instead.
    probe_resolve_value: Optional[str] = None
    # Parent field to percent-encode into the fan-out `resolve_field`, for a parent value that is
    # free text bound into the child path's query string.
    encode_parent_field: Optional[str] = None
    # Endpoint to probe for permissions instead of this one, when this response is too large to
    # download on every schema-picker load. It must read with the same scope.
    probe_endpoint: Optional[str] = None


# Marketing Campaigns is provisioned per account, and legacy Marketing Campaigns serves a different
# API entirely, so both deny the `/marketing` endpoints however the key is scoped.
_MARKETING_CAMPAIGNS_NOTE = (
    "Accounts without Marketing Campaigns, or on legacy Marketing Campaigns, cannot sync this table."
)


def _epoch_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.Integer,
        "field": name,
        "field_type": IncrementalFieldType.Integer,
    }


def _date_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.Date,
        "field": name,
        "field_type": IncrementalFieldType.Date,
    }


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# SendGrid (v3) endpoint catalog. The suppression endpoints expose a genuine server-side
# `start_time` filter (Unix epoch seconds) over their immutable `created` field, so they sync
# incrementally. `stats` and `category_stats` filter on `start_date` (YYYY-MM-DD) over their daily
# aggregate date and also sync incrementally. Marketing/asm metadata endpoints offer no timestamp filter and ship as
# full refresh. See api_inventory.md for the per-endpoint research notes.
SENDGRID_ENDPOINTS: dict[str, SendGridEndpointConfig] = {
    "bounces": SendGridEndpointConfig(
        name="bounces",
        path="/suppression/bounces",
        primary_keys=["email"],
        pagination="offset",
        partition_key="created",
        incremental_fields=[_epoch_field("created")],
        incremental_param="start_time",
        required_scope="suppression.bounces.read",
    ),
    "blocks": SendGridEndpointConfig(
        name="blocks",
        path="/suppression/blocks",
        primary_keys=["email"],
        pagination="offset",
        partition_key="created",
        incremental_fields=[_epoch_field("created")],
        incremental_param="start_time",
        required_scope="suppression.blocks.read",
    ),
    "invalid_emails": SendGridEndpointConfig(
        name="invalid_emails",
        path="/suppression/invalid_emails",
        primary_keys=["email"],
        pagination="offset",
        partition_key="created",
        incremental_fields=[_epoch_field("created")],
        incremental_param="start_time",
        required_scope="suppression.invalid_emails.read",
    ),
    "spam_reports": SendGridEndpointConfig(
        name="spam_reports",
        path="/suppression/spam_reports",
        primary_keys=["email"],
        pagination="offset",
        partition_key="created",
        incremental_fields=[_epoch_field("created")],
        incremental_param="start_time",
        required_scope="suppression.spam_reports.read",
    ),
    "global_unsubscribes": SendGridEndpointConfig(
        name="global_unsubscribes",
        path="/suppression/unsubscribes",
        primary_keys=["email"],
        pagination="offset",
        partition_key="created",
        incremental_fields=[_epoch_field("created")],
        incremental_param="start_time",
        required_scope="suppression.unsubscribes.read",
    ),
    "stats": SendGridEndpointConfig(
        name="stats",
        path="/stats",
        primary_keys=["date"],
        # /stats returns the whole date range in one bare-array response — no pagination params.
        pagination="single",
        partition_key="date",
        incremental_fields=[_date_field("date")],
        # start_date is a genuine server-side filter, so this endpoint syncs incrementally on the
        # daily aggregate date. start_date is required, so a cursorless sync backfills a fixed window.
        incremental_param="start_date",
        incremental_param_format="date",
        default_backfill_days=STATS_DEFAULT_BACKFILL_DAYS,
        response_shape="daily_stats",
        extra_params={"aggregated_by": "day"},
        required_scope="stats.read",
    ),
    "categories": SendGridEndpointConfig(
        name="categories",
        path="/categories",
        primary_keys=["category"],
        pagination="offset",
        # The documented default. No maximum is documented, and a silently capped page would read
        # as the short last page and end the walk early.
        page_size=50,
        required_scope="categories.read",
    ),
    # /categories/stats requires the `categories` param, so it fans out over the category listing
    # one category per request. The listing reads with a different scope, so the probe hits this
    # path itself.
    "category_stats": SendGridEndpointConfig(
        name="category_stats",
        path="/categories/stats?categories={category}",
        primary_keys=["category", "date"],
        pagination="single",
        partition_key="date",
        incremental_fields=[_date_field("date")],
        incremental_param="start_date",
        incremental_param_format="date",
        default_backfill_days=STATS_DEFAULT_BACKFILL_DAYS,
        response_shape="category_stats",
        sort_mode=None,
        extra_params={"aggregated_by": "day"},
        required_scope="categories.stats.read",
        default_incremental_field="date",
        fanout=DependentEndpointConfig(
            parent_name="categories",
            resolve_param="category",
            resolve_field="category_param",
            include_from_parent=["category"],
            parent_field_renames={"category": "category"},
        ),
        probe_resolve_value="posthog",
        # Category names are free text, and the resolved value is bound into the path unescaped.
        encode_parent_field="category",
    ),
    "unsubscribe_groups": SendGridEndpointConfig(
        name="unsubscribe_groups",
        path="/asm/groups",
        primary_keys=["id"],
        pagination="single",
        required_scope="asm.groups.read",
    ),
    # Membership rows of every unsubscribe group in one response. This is the same data as a
    # per-group fan-out over /asm/groups/{group_id}/suppressions, which returns bare email strings
    # with no creation time.
    "unsubscribe_group_suppressions": SendGridEndpointConfig(
        name="unsubscribe_group_suppressions",
        path="/asm/suppressions",
        primary_keys=["group_id", "email"],
        pagination="single",
        partition_key="created_at",
        required_scope="asm.groups.read",
        probe_endpoint="unsubscribe_groups",
    ),
    "marketing_lists": SendGridEndpointConfig(
        name="marketing_lists",
        path="/marketing/lists",
        primary_keys=["id"],
        pagination="metadata",
        data_key="result",
        page_size=100,
        required_scope="marketing.read",
        permission_note=_MARKETING_CAMPAIGNS_NOTE,
    ),
    "singlesends": SendGridEndpointConfig(
        name="singlesends",
        path="/marketing/singlesends",
        primary_keys=["id"],
        pagination="metadata",
        data_key="result",
        page_size=100,
        partition_key="created_at",
        required_scope="marketing.read",
        permission_note=_MARKETING_CAMPAIGNS_NOTE,
    ),
    "singlesend_stats": SendGridEndpointConfig(
        name="singlesend_stats",
        path="/marketing/stats/singlesends",
        # Without `group_by`, ab_variation and ab_phase are "all", so each single send has one
        # lifetime-total row. They stay in the key so an A/B breakdown row can never collide.
        primary_keys=["id", "ab_variation", "ab_phase"],
        pagination="metadata",
        data_key="results",
        # The stats endpoints cap `page_size` at 50.
        page_size=50,
        required_scope="marketing.read",
        permission_note=_MARKETING_CAMPAIGNS_NOTE,
    ),
    "singlesend_link_stats": SendGridEndpointConfig(
        name="singlesend_link_stats",
        path="/marketing/stats/singlesends/{singlesend_id}/links",
        primary_keys=["singlesend_id", "url", "url_location", "ab_variation", "ab_phase"],
        pagination="metadata",
        data_key="results",
        page_size=50,
        required_scope="marketing.read",
        permission_note=_MARKETING_CAMPAIGNS_NOTE,
        fanout=DependentEndpointConfig(
            parent_name="singlesends",
            resolve_param="singlesend_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "singlesend_id"},
            # A single send deleted between the parent listing and its child fetch must not fail
            # the whole table.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "automation_stats": SendGridEndpointConfig(
        name="automation_stats",
        path="/marketing/stats/automations",
        # Without `group_by`, step_id is "all" and aggregation is "total", so each automation has
        # one lifetime-total row. They stay in the key so a per-step or per-day row can never collide.
        primary_keys=["id", "aggregation", "step_id"],
        pagination="metadata",
        data_key="results",
        page_size=50,
        required_scope="marketing.read",
        permission_note=_MARKETING_CAMPAIGNS_NOTE,
    ),
    # The API has no automation listing, so the stats rows supply the automation ids.
    "automation_link_stats": SendGridEndpointConfig(
        name="automation_link_stats",
        path="/marketing/stats/automations/{automation_id}/links",
        primary_keys=["automation_id", "url", "url_location", "step_id"],
        pagination="metadata",
        data_key="results",
        page_size=50,
        required_scope="marketing.read",
        permission_note=_MARKETING_CAMPAIGNS_NOTE,
        fanout=DependentEndpointConfig(
            parent_name="automation_stats",
            resolve_param="automation_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "automation_id"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "templates": SendGridEndpointConfig(
        name="templates",
        path="/templates",
        primary_keys=["id"],
        pagination="metadata",
        data_key="result",
        page_size=100,
        extra_params={"generations": "legacy,dynamic"},
        required_scope="templates.read",
    ),
    "message_activity": SendGridEndpointConfig(
        name="message_activity",
        path="/messages",
        primary_keys=["msg_id"],
        pagination="activity",
        data_key="messages",
        # /messages caps `limit` at 1000. No partition key: a message's only timestamp,
        # last_event_time, advances whenever a new event lands, so partitions would rewrite.
        page_size=1000,
        incremental_fields=[_datetime_field("last_event_time")],
        sort_mode="desc",
        # Gated behind a paid add-on most accounts don't have, so it must be an explicit opt-in.
        should_sync_default=False,
        required_scope="email_activity.read",
        permission_note=(
            "Accounts without SendGrid's paid additional email activity history add-on cannot sync "
            "this table, even with the Email Activity scope granted."
        ),
    ),
}

ENDPOINTS = tuple(SENDGRID_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SENDGRID_ENDPOINTS.items() if config.incremental_fields
}

SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: config.should_sync_default for name, config in SENDGRID_ENDPOINTS.items()}
