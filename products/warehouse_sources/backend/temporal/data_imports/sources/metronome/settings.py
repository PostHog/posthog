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

# Every paginated Metronome list endpoint caps `limit` at 100.
PAGE_SIZE = 100

# List responses share a `{"data": [...], "next_page": "..."}` envelope, and the cursor goes back
# out under the name it arrived under.
DATA_SELECTOR = "data"
CURSOR_PATH = "next_page"
CURSOR_PARAM = "next_page"

# `GET /v1/auditLogs` is the only endpoint with a server-side lower bound on record time.
AUDIT_LOG_START_PARAM = "starting_on"

# How `POST /v1/usage` aggregates the period it is asked for: one row per hour, one row per day, or
# one row for the whole period.
WindowSize = Literal["none", "hour", "day"]

# How far back a first sync of each bucketed usage table reaches. A bucketed table holds one row per
# customer, billable metric and period, so its size is the account's customer/metric pairs
# multiplied by the number of periods. The hourly table holds 24 rows for every daily row, so it
# reaches back less far.
USAGE_DAILY_HISTORY = timedelta(days=365)
USAGE_HOURLY_HISTORY = timedelta(days=30)

# Metronome accepts usage events backdated up to 34 days, so a period that already synced can still
# change. Each incremental run re-reads this much of the period it already covered and upserts it.
USAGE_DAILY_LOOKBACK_SECONDS = 7 * 24 * 60 * 60
USAGE_HOURLY_LOOKBACK_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class BodyFanoutConfig:
    """Fan-out whose parent id belongs in the child's JSON body.

    The declarative fan-out helper binds a resolved parent field into the child's *path* only, so
    a child like `POST /v2/contracts/list` — which takes `customer_id` in its body — walks the
    parent itself instead.
    """

    parent_name: str
    resolve_field: str
    body_param: str


# frozen=False: MetronomeEndpointConfig is passed as `endpoint_configs: Mapping[str, FanoutEndpointLike]`,
# and mypy treats a frozen dataclass's fields as read-only, which is incompatible with that
# Protocol's plain (read-write) attributes.
@dataclass(frozen=False)
class MetronomeEndpointConfig:
    name: str
    path: str
    primary_key: list[str]
    method: Literal["get", "post"] = "get"
    # Filter payload for the POST list endpoints. `limit` and `next_page` stay in the query string
    # on these; only the filters move into the body.
    json_body: dict[str, Any] = field(default_factory=dict)
    extra_params: dict[str, Any] = field(default_factory=dict)
    # Endpoints whose response carries a `next_page` cursor; the rest return the whole collection.
    paginated: bool = True
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
    # window is computed per run, because `ending_before` is the sync time, so it can't live in the
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
    "contracts": MetronomeEndpointConfig(
        name="contracts",
        path="/v2/contracts/list",
        method="post",
        primary_key=["id"],
        partition_key="created_at",
        # Returns every contract for the customer in one response — no cursor, no `limit`.
        paginated=False,
        json_body={"include_archived": True},
        body_fanout=BodyFanoutConfig(parent_name="customers", resolve_field="id", body_param="customer_id"),
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

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in METRONOME_ENDPOINTS.items()
}
