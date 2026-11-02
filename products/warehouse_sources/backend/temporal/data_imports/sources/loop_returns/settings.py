from dataclasses import dataclass

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Loop documents a 120-day maximum for a list request's `from`/`to` range.
API_MAX_RANGE_DAYS = 120

# How wide a window actually asks for. A range whose bounds sit exactly the documented maximum
# apart is rejected with a 422, and Loop doesn't say where its off-by-one is, so a window keeps a
# margin under the cap. A quarter matches the range in Loop's own example request and costs a
# couple of extra requests per backfill.
MAX_WINDOW_DAYS = 90

# `pageSize` accepts up to 750. Return rows carry nested line items, exchanges and labels, so we
# stay well under the cap to keep a single page's payload modest.
DEFAULT_PAGE_SIZE = 250

# `limit` cap on the cursor-paginated catalog endpoints (orders, products, product variants and
# customers). Loop documents 250 as the maximum on orders, customers and product variants.
CURSOR_PAGE_SIZE = 250

# How far back a first sync reaches when the user doesn't give a start date. Without `from`/`to`
# Loop only returns the previous 24 hours, so a default is required for a usable backfill.
DEFAULT_BACKFILL_DAYS = 730

# The furthest back a configured start date may reach. A backfill walks history one window per
# state pass, so an unbounded start date turns a single sync into thousands of empty-window
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
    # Cursor pagination through `limit`/`cursor` with a `next_page_url` in the body.
    cursor_paginate: bool = False
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
    # Endpoint whose row `id` fills the `{parent_id}` path placeholder, one request per parent row.
    parent: str | None = None
    # Column that carries the parent row's `id` on each child row.
    parent_id_column: str = "parent_id"


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
    "orders": LoopReturnsEndpointConfig(
        name="orders",
        path="/orders",
        primary_keys=("id",),
        data_selector="orders",
        cursor_paginate=True,
        partition_key="created_at",
        required_scope="Order (Read)",
    ),
    "products": LoopReturnsEndpointConfig(
        name="products",
        path="/products",
        primary_keys=("id",),
        data_selector="products",
        cursor_paginate=True,
        partition_key="created_at",
        required_scope="Product (Read)",
    ),
    "product_variants": LoopReturnsEndpointConfig(
        name="product_variants",
        path="/products/{parent_id}/product-variants",
        # Rows from every product land in one table, and the docs don't say that a variant id is
        # unique across products, so the parent product id is part of the key.
        primary_keys=("product_id", "id"),
        data_selector="product_variants",
        cursor_paginate=True,
        required_scope="Product (Read)",
        parent="products",
        parent_id_column="product_id",
    ),
    "customers": LoopReturnsEndpointConfig(
        name="customers",
        path="/customers",
        primary_keys=("id",),
        data_selector="customers",
        cursor_paginate=True,
        required_scope="Customers (Read)",
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
