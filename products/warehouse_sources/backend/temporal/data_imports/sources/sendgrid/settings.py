from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How a list endpoint is walked:
# - "offset":   `limit`/`offset` query params over a bare JSON array (suppression endpoints).
# - "metadata": follow the absolute `_metadata.next` URL the API returns (marketing endpoints).
# - "single":   one request returns the whole list, no pagination params.
PaginationMode = Literal["offset", "metadata", "single"]

# How the incremental cursor is serialized into the `incremental_param` query value:
# - "epoch": Unix epoch seconds (suppression `start_time`).
# - "date":  `YYYY-MM-DD` (stats `start_date`).
IncrementalParamFormat = Literal["epoch", "date"]

# Shape of a 200 response body, so the transport knows whether it needs flattening:
# - "array":       the rows are the JSON body itself, or the array under `data_key`.
# - "daily_stats": nested `[{date, stats: [{metrics: {...}}]}]` that flattens to one row per
#                  metrics bucket with `date` merged in (the /stats family).
ResponseShape = Literal["array", "daily_stats"]

# /stats requires `start_date` on every request, so the first sync (no cursor yet) backfills this
# far back. Daily aggregation means one row per day, so a year is cheap and gives enough history to
# compare deliverability trends.
STATS_DEFAULT_BACKFILL_DAYS = 365


@dataclass
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
    # Static query params always sent (e.g. templates' `generations`).
    extra_params: dict[str, str] = field(default_factory=dict)
    # SendGrid scope this endpoint reads, spelled as `/scopes` reports it. Surfaced per table in the
    # schema picker when the key can't reach the endpoint, so the user grants that one access rather
    # than regenerating a key that was never the problem.
    required_scope: str = ""
    # Appended to the missing-scope message where granting the scope may not be enough on its own.
    permission_note: Optional[str] = None


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


# SendGrid (v3) endpoint catalog. The suppression endpoints expose a genuine server-side
# `start_time` filter (Unix epoch seconds) over their immutable `created` field, so they sync
# incrementally. `stats` filters on `start_date` (YYYY-MM-DD) over its daily aggregate date and
# also syncs incrementally. Marketing/asm metadata endpoints offer no timestamp filter and ship as
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
    "unsubscribe_groups": SendGridEndpointConfig(
        name="unsubscribe_groups",
        path="/asm/groups",
        primary_keys=["id"],
        pagination="single",
        required_scope="asm.groups.read",
    ),
    "marketing_lists": SendGridEndpointConfig(
        name="marketing_lists",
        path="/marketing/lists",
        primary_keys=["id"],
        pagination="metadata",
        data_key="result",
        page_size=100,
        required_scope="marketing.read",
        # Marketing Campaigns is provisioned per account, and legacy Marketing Campaigns serves a
        # different API entirely, so both deny `/marketing/lists` however the key is scoped.
        permission_note="Accounts without Marketing Campaigns, or on legacy Marketing Campaigns, cannot sync this table.",
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
}

ENDPOINTS = tuple(SENDGRID_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SENDGRID_ENDPOINTS.items() if config.incremental_fields
}
