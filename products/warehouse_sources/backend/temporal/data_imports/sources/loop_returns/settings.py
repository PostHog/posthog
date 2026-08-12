from dataclasses import dataclass

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Loop rejects a list request whose `from`/`to` range is wider than 120 days, so backfills walk
# the history in windows of at most this size.
MAX_WINDOW_DAYS = 120

# `pageSize` accepts up to 750. Return rows carry nested line items, exchanges and labels, so we
# stay well under the cap to keep a single page's payload modest.
DEFAULT_PAGE_SIZE = 250

# How far back a first sync reaches when the user doesn't give a start date. Without `from`/`to`
# Loop only returns the previous 24 hours, so a default is required for a usable backfill.
DEFAULT_BACKFILL_DAYS = 730

# The furthest back a configured start date may reach. A backfill walks history one 120-day window
# per state pass, so an unbounded start date turns a single sync into thousands of empty-window
# requests that tie up a worker. Cap the lookback at validation time instead.
MAX_BACKFILL_DAYS = 5 * 365

# `state` is a single-valued enum and, when omitted, Loop returns only open, closed and expired
# returns. Each state is fetched as its own pass so cancelled and in-review returns land too.
RETURN_STATES = ("open", "closed", "cancelled", "expired", "review")

# The `filter` param picks which timestamp `from`/`to` apply to.
FILTER_FIELDS = ("created_at", "updated_at")


@dataclass(frozen=True)
class LoopReturnsEndpointConfig:
    name: str
    path: str
    primary_keys: tuple[str, ...]
    # Key holding the row array; `None` for endpoints that return a bare array.
    data_selector: str | None = None
    # Cursor pagination through `paginate`/`pageSize` with a `nextPageUrl` in the body.
    paginate: bool = False
    # Endpoint accepts `from`/`to`, so history is walked in windows.
    windowed: bool = False
    # States fetched one pass each; empty means the endpoint has no `state` param.
    states: tuple[str, ...] = ()
    # Whether the endpoint accepts the `filter` param that selects the windowed timestamp.
    supports_filter_param: bool = False
    # Stable creation timestamp to partition on; `None` disables partitioning.
    partition_key: str | None = None
    # API key scope the endpoint needs, as named in Loop's dashboard.
    required_scope: str = "Returns"


LOOP_RETURNS_ENDPOINTS: dict[str, LoopReturnsEndpointConfig] = {
    "returns": LoopReturnsEndpointConfig(
        name="returns",
        path="/warehouse/return/list",
        primary_keys=("id",),
        data_selector="returns",
        paginate=True,
        windowed=True,
        states=RETURN_STATES,
        supports_filter_param=True,
        partition_key="created_at",
    ),
    "advanced_shipping_notices": LoopReturnsEndpointConfig(
        name="advanced_shipping_notices",
        path="/warehouse/reporting/asn",
        # One row per returned line item. `id` looks like a per-row identifier, but the docs don't
        # state that it is unique across the report, so the line item id is part of the key — a key
        # that is unique per parent only would seed duplicates that every later merge multi-matches.
        primary_keys=("id", "return_line_item_id"),
        windowed=True,
        partition_key="created_at",
    ),
    "destinations": LoopReturnsEndpointConfig(
        name="destinations",
        path="/destinations",
        primary_keys=("id",),
        data_selector="destinations",
        required_scope="Destinations (Read)",
    ),
}

ENDPOINTS = tuple(LOOP_RETURNS_ENDPOINTS)

# `returns` windows on either timestamp via the `filter` param. The ASN report takes `from`/`to`
# but doesn't document which timestamp they apply to, so only `created_at` is advertised there:
# whichever timestamp the server filters on, a window starting at the highest `created_at` we have
# still contains every row created after it.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "returns": [incremental_field("created_at"), incremental_field("updated_at")],
    "advanced_shipping_notices": [incremental_field("created_at")],
}
