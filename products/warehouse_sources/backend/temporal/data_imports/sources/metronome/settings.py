from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

METRONOME_BASE_URL = "https://api.metronome.com"

# Metronome caps `limit` at 100 on every list endpoint that accepts it.
PAGE_SIZE = 100

# List responses share a `{"data": [...], "next_page": "..."}` envelope, and the cursor goes back
# out under the name it arrived under.
DATA_SELECTOR = "data"
CURSOR_PATH = "next_page"
CURSOR_PARAM = "next_page"

# `GET /v1/auditLogs` is the only endpoint with a server-side lower bound on record time.
AUDIT_LOG_START_PARAM = "starting_on"

# `POST /v1/contracts/customerBalances/list` caps `limit` at 25.
BALANCES_PAGE_SIZE = 25

# Lower bound for a request that asks for a whole schedule — earlier than any Metronome account.
EPOCH_RFC_3339 = "1970-01-01T00:00:00Z"

# How far back a first sync of `invoice_breakdowns` reaches. It holds one row per invoice and day, so
# like the daily usage table it reaches back a year rather than to the start of the account.
INVOICE_BREAKDOWNS_HISTORY = timedelta(days=365)
# Backdated usage changes a breakdown after its day has passed, and a draft invoice keeps changing
# until it finalizes, so each incremental run re-reads this much of what it already covered.
INVOICE_BREAKDOWNS_LOOKBACK_SECONDS = 7 * 24 * 60 * 60

# How `POST /v1/usage` aggregates the period it is asked for: one row per hour, one row per day, or
# one row for the whole period.
WindowSize = Literal["none", "hour", "day"]

# How far back a first sync of each bucketed usage table reaches. A bucketed table holds one row per
# customer, billable metric and period, so its size is the account's customer/metric pairs
# multiplied by the number of periods. The hourly table holds 24 rows for every daily row, so it
# reaches back less far.
USAGE_DAILY_HISTORY = timedelta(days=365)
USAGE_HOURLY_HISTORY = timedelta(days=30)

# The depths a user can pick per source. `POST /v1/usage` takes no page-size parameter and pages per
# customer and billable metric, so a first sync costs one request per page whatever the account's
# size, and depth is the only lever over how long that sync takes. The daily table is labelled in
# months because that is the grain people reason about it in; twelve months is 365 days, which is
# what this source shipped with.
DEFAULT_USAGE_HOURLY_HISTORY_DAYS = 30
DEFAULT_USAGE_DAILY_HISTORY_MONTHS = 12
# Upper bounds, because a depth the endpoint cannot get through in one sync leaves the table empty
# rather than shallow, which reads to the user as broken rather than as a setting they chose.
MAX_USAGE_HOURLY_HISTORY_DAYS = 30
MAX_USAGE_DAILY_HISTORY_MONTHS = 24
# A month has no fixed length. This is the average that keeps twelve months at the 365 days this
# source shipped with, so an unset daily depth reads exactly the window it read before.
DAYS_PER_MONTH = 365 / 12


def _bounded(value: int | None, default: int, highest: int) -> int:
    """An unset depth reads the default; one outside the range is held to it rather than dropped."""
    if value is None:
        return default
    return max(1, min(value, highest))


def usage_history_window(schema_name: str, hourly_days: int | None, daily_months: int | None) -> timedelta | None:
    """How far back a first sync of one bucketed usage table reaches."""
    if schema_name == "usage_hourly":
        return timedelta(days=_bounded(hourly_days, DEFAULT_USAGE_HOURLY_HISTORY_DAYS, MAX_USAGE_HOURLY_HISTORY_DAYS))
    if schema_name == "usage_daily":
        months = _bounded(daily_months, DEFAULT_USAGE_DAILY_HISTORY_MONTHS, MAX_USAGE_DAILY_HISTORY_MONTHS)
        return timedelta(days=months * DAYS_PER_MONTH)
    return None


# Metronome accepts usage events backdated up to 34 days, so a period that already synced can still
# change. Each incremental run re-reads this much of the period it already covered and upserts it.
USAGE_DAILY_LOOKBACK_SECONDS = 7 * 24 * 60 * 60
USAGE_HOURLY_LOOKBACK_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class BodyFanoutConfig:
    """Fan-out whose parent ids belong in the child's JSON body.

    The declarative fan-out helper binds a resolved parent field into the child's *path* only, so
    a child like `POST /v2/contracts/list` — which takes `customer_id` in its body — walks the
    parent itself instead. The parent can itself be a body fan-out, which chains the walk.
    """

    parent_name: str
    # Child body param -> the parent row field it is read from. Each one is also copied onto the
    # child rows that lack it, because several children never echo back the ids they were asked for.
    body_params: dict[str, str]
    # Parent rows that have this field set are skipped.
    skip_parents_with: str | None = None


# frozen=False: MetronomeEndpointConfig is passed as `endpoint_configs: Mapping[str, FanoutEndpointLike]`,
# and mypy treats a frozen dataclass's fields as read-only, which is incompatible with that
# Protocol's plain (read-write) attributes.
@dataclass(frozen=False)
class MetronomeEndpointConfig:
    name: str
    path: str
    primary_key: list[str]
    method: Literal["get", "post"] = "get"
    # Filter payload for the POST list endpoints. Only the filters move into the body, and
    # `next_page` stays in the query string. See `accepts_page_size` for whether `limit` joins it.
    json_body: dict[str, Any] = field(default_factory=dict)
    extra_params: dict[str, Any] = field(default_factory=dict)
    # Endpoints whose response carries a `next_page` cursor; the rest return the whole collection.
    paginated: bool = True
    # Where `limit` and `next_page` go. `POST /v1/contracts/customerBalances/list` reads both from
    # the body and ignores them in the query string.
    page_param_location: Literal["query", "json"] = "query"
    # Whether the endpoint takes a `limit` page-size parameter. `POST /v1/usage` follows
    # `next_page` but rejects `limit`, and answers the whole request with a 400 when it is
    # present. Following the cursor and setting a page size are separate capabilities, so
    # `paginated` must not decide both.
    accepts_page_size: bool = True
    # Server-side lower bound for incremental syncs. Metronome rejects this window when a cursor
    # is also sent, so it only rides the first request of a run.
    incremental_start_param: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    partition_key: str | None = None
    page_size: int = PAGE_SIZE
    fanout: DependentEndpointConfig | None = None
    body_fanout: BodyFanoutConfig | None = None
    # `POST /v1/usage` needs a `window_size`/`starting_on`/`ending_before` window in its body. The
    # window is computed per run, because `ending_before` tracks the clock, so it can't live in the
    # static `json_body`. When set, the resource builder fills the window in. None means the
    # endpoint sends no window.
    window_size: WindowSize | None = None
    # The order rows are emitted in. `POST /v1/usage` groups its rows by customer and billable
    # metric rather than by time, so a bucketed table declares "desc" to hold the incremental
    # watermark back until the walk finishes. Committing it per batch would advance it to the newest
    # period of the first customer walked, and the next run would then skip every older period the
    # remaining customers still owe.
    sort_mode: SortMode = "asc"
    should_sync_default: bool = True
    default_incremental_lookback_seconds: int | None = None
    # A fan-out child whose query needs a `starting_on`/`ending_before` window. This is how far back
    # a run with no watermark reaches. None means the endpoint sends no window.
    query_window_history: timedelta | None = None
    # Derives `pricing_group_key` on rate schedule rows, whose identity includes an object column.
    keys_pricing_group: bool = False


# Customer-scoped children bind the parent's `id` into their path as `customer_id`. Every child
# row already carries its own `customer_id`, so nothing needs copying down from the parent.
_CUSTOMER_PATH_FANOUT = DependentEndpointConfig(
    parent_name="customers",
    resolve_param="customer_id",
    resolve_field="id",
    include_from_parent=[],
)


METRONOME_ENDPOINTS: dict[str, MetronomeEndpointConfig] = {
    "customers": MetronomeEndpointConfig(
        name="customers",
        path="/v1/customers",
        primary_key=["id"],
        partition_key="created_at",
        # No created/updated filter exists on this endpoint, so every run reads the whole list.
        # `only_archived` swaps the result set rather than widening it, so archived customers are
        # out of scope for this table.
    ),
    "invoices": MetronomeEndpointConfig(
        name="invoices",
        path="/v1/customers/{customer_id}/invoices",
        primary_key=["id"],
        # The endpoint's own docs give two different default orders, so pin one.
        extra_params={"sort": "date_asc"},
        # `line_items` is unbounded, so a full page of invoices can be very large. A smaller page
        # keeps each response, and the Arrow table built from it, within reach.
        page_size=25,
        fanout=_CUSTOMER_PATH_FANOUT,
    ),
    # One row per invoice and day. Starts off, because a first sync is one walk per customer over a
    # year of days.
    "invoice_breakdowns": MetronomeEndpointConfig(
        name="invoice_breakdowns",
        path="/v1/customers/{customer_id}/invoices/breakdowns",
        primary_key=["id", "breakdown_start_timestamp"],
        partition_key="breakdown_start_timestamp",
        page_size=25,
        # `sort` orders the invoices by issue date, so rows still arrive grouped by customer rather
        # than by period, and the watermark is held back until the walk ends, like `usage_daily`.
        extra_params={"window_size": "DAY", "sort": "date_asc"},
        fanout=_CUSTOMER_PATH_FANOUT,
        incremental_fields=[incremental_field("breakdown_start_timestamp")],
        default_incremental_field="breakdown_start_timestamp",
        default_incremental_lookback_seconds=INVOICE_BREAKDOWNS_LOOKBACK_SECONDS,
        query_window_history=INVOICE_BREAKDOWNS_HISTORY,
        sort_mode="desc",
        should_sync_default=False,
    ),
    "contracts": MetronomeEndpointConfig(
        name="contracts",
        path="/v2/contracts/list",
        method="post",
        primary_key=["id"],
        partition_key="created_at",
        # Returns every contract for the customer in one response — no cursor, no `limit`.
        paginated=False,
        json_body={"include_archived": True},
        body_fanout=BodyFanoutConfig(parent_name="customers", body_params={"customer_id": "id"}),
    ),
    "balances": MetronomeEndpointConfig(
        name="balances",
        path="/v1/contracts/customerBalances/list",
        method="post",
        # A commit or credit id is a UUID, but the rows come from one walk per customer, so the
        # customer joins the key rather than relying on that.
        primary_key=["customer_id", "id"],
        page_size=BALANCES_PAGE_SIZE,
        page_param_location="json",
        # Ledgers and balances are off by default. Both are what this table exists for.
        json_body={
            "include_archived": True,
            "include_balance": True,
            "include_contract_balances": True,
            "include_ledgers": True,
        },
        body_fanout=BodyFanoutConfig(parent_name="customers", body_params={"customer_id": "id"}),
    ),
    # The rates in effect now on each live contract, with the contract's overrides applied. The
    # endpoint answers for one point in time only, so the table is a current snapshot. It takes one
    # walk per contract, so it starts off.
    "contract_rate_schedules": MetronomeEndpointConfig(
        name="contract_rate_schedules",
        path="/v1/contracts/getContractRateSchedule",
        method="post",
        primary_key=["contract_id", "product_id", "pricing_group_key", "billing_frequency", "starting_at"],
        body_fanout=BodyFanoutConfig(
            parent_name="contracts",
            body_params={"customer_id": "customer_id", "contract_id": "id"},
            # An archived contract bills nothing, so it has no rates in effect to report.
            skip_parents_with="archived_at",
        ),
        keys_pricing_group=True,
        should_sync_default=False,
    ),
    "products": MetronomeEndpointConfig(
        name="products",
        path="/v1/contract-pricing/products/list",
        method="post",
        primary_key=["id"],
        # Archived products stay in the warehouse copy; the default filter hides them.
        json_body={"archive_filter": "ALL"},
    ),
    "rate_cards": MetronomeEndpointConfig(
        name="rate_cards",
        path="/v1/contract-pricing/rate-cards/list",
        method="post",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "rate_card_rate_schedules": MetronomeEndpointConfig(
        name="rate_card_rate_schedules",
        path="/v1/contract-pricing/rate-cards/getRateSchedule",
        method="post",
        # A rate carries no id. It is one product's price for one pricing group and billing
        # frequency, from one point in time.
        primary_key=["rate_card_id", "product_id", "pricing_group_key", "billing_frequency", "starting_at"],
        # `starting_at` is required. The epoch asks for every segment, past and scheduled.
        json_body={"starting_at": EPOCH_RFC_3339},
        body_fanout=BodyFanoutConfig(parent_name="rate_cards", body_params={"rate_card_id": "id"}),
        keys_pricing_group=True,
    ),
    "packages": MetronomeEndpointConfig(
        name="packages",
        path="/v1/packages/list",
        method="post",
        primary_key=["id"],
        partition_key="created_at",
        json_body={"archive_filter": "ALL"},
    ),
    "billable_metrics": MetronomeEndpointConfig(
        name="billable_metrics",
        path="/v1/billable-metrics",
        primary_key=["id"],
        extra_params={"include_archived": "true"},
    ),
    "pricing_units": MetronomeEndpointConfig(
        name="pricing_units",
        path="/v1/credit-types/list",
        primary_key=["id"],
    ),
    "plans": MetronomeEndpointConfig(
        name="plans",
        path="/v1/plans",
        primary_key=["id"],
        # Deprecated by Metronome in favor of contracts, but still the only place a customer's
        # plan is named. No created/updated filter, so every run reads the whole list.
    ),
    "usage": MetronomeEndpointConfig(
        name="usage",
        path="/v1/usage",
        method="post",
        # One aggregate per customer and billable metric — the endpoint carries no row id.
        primary_key=["customer_id", "billable_metric_id"],
        accepts_page_size=False,
        # `none` returns a single lifetime aggregate per customer/metric over the requested window,
        # which starts at the epoch, so the row count stays bounded by the account. The two tables
        # below carry the same usage split into periods, over a window bounded per table.
        window_size="none",
    ),
    # Both bucketed tables start off: a first sync of either is far larger than the whole rest of
    # the catalog, and the lifetime `usage` table above already answers the common question.
    "usage_daily": MetronomeEndpointConfig(
        name="usage_daily",
        path="/v1/usage",
        method="post",
        # One row per customer, billable metric and day, so the period joins the key that the
        # lifetime table identifies a row by.
        primary_key=["customer_id", "billable_metric_id", "start_timestamp"],
        partition_key="start_timestamp",
        accepts_page_size=False,
        window_size="day",
        incremental_fields=[incremental_field("start_timestamp")],
        default_incremental_field="start_timestamp",
        default_incremental_lookback_seconds=USAGE_DAILY_LOOKBACK_SECONDS,
        sort_mode="desc",
        should_sync_default=False,
    ),
    "usage_hourly": MetronomeEndpointConfig(
        name="usage_hourly",
        path="/v1/usage",
        method="post",
        primary_key=["customer_id", "billable_metric_id", "start_timestamp"],
        partition_key="start_timestamp",
        accepts_page_size=False,
        window_size="hour",
        incremental_fields=[incremental_field("start_timestamp")],
        default_incremental_field="start_timestamp",
        default_incremental_lookback_seconds=USAGE_HOURLY_LOOKBACK_SECONDS,
        sort_mode="desc",
        should_sync_default=False,
    ),
    "audit_logs": MetronomeEndpointConfig(
        name="audit_logs",
        path="/v1/auditLogs",
        primary_key=["id"],
        # `date_asc` is the documented default, but pin it so the rows arrive in the order the
        # incremental watermark assumes.
        extra_params={"sort": "date_asc"},
        incremental_start_param=AUDIT_LOG_START_PARAM,
        incremental_fields=[incremental_field("timestamp")],
        default_incremental_field="timestamp",
        partition_key="timestamp",
    ),
}

ENDPOINTS = tuple(METRONOME_ENDPOINTS)

# The tables whose rows are one usage period, with how far back a first sync of each one reaches.
USAGE_HISTORY: dict[str, timedelta] = {
    "usage_daily": USAGE_DAILY_HISTORY,
    "usage_hourly": USAGE_HOURLY_HISTORY,
}

# Tables whose incremental runs re-read periods they already hold, so they merge and never append.
MERGE_ONLY = (*USAGE_HISTORY, "invoice_breakdowns")

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in METRONOME_ENDPOINTS.items()
}
