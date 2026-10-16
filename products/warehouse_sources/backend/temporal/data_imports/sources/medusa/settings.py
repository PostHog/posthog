from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Medusa's list routes default `limit` to 20-50 and document no hard maximum; 100 keeps pages
# moderate for wide rows (orders carry items, addresses and totals inline).
PAGE_SIZE = 100

# Medusa ids are globally unique prefixed identifiers (`order_...`, `prod_...`), so `id` alone
# is unique table-wide on every endpoint below.
PRIMARY_KEYS = ("id",)

# Every Medusa entity carries an immutable `created_at`, which makes it a stable partition key
# (`updated_at` changes on every write and would rewrite partitions each sync).
PARTITION_KEY = "created_at"

REQUEST_TIMEOUT_SECONDS = 30.0

# Split connect/read timeouts for the sync path, threaded through the client's
# `request_timeout` (with a session-level fallback): without them a user-controlled host
# could accept the connection and then leave a response unfinished, occupying an import
# worker until the resumable activity's week-long timeout.
CONNECT_TIMEOUT_SECONDS = 10.0
READ_TIMEOUT_SECONDS = 60.0

# Hard wall-clock ceiling on delivering a single response body. READ_TIMEOUT_SECONDS is only a
# socket-inactivity timeout: a host that drips a byte before each idle window keeps the read
# blocked indefinitely while staying under the byte cap. The body is read on a daemon thread
# that is abandoned past this deadline (closing the response to unblock the socket).
READ_DEADLINE_SECONDS = 180.0

# Hard per-response cap on decoded body bytes. `requests` buffers and decodes the whole body
# before returning, so a hostile host could return an arbitrarily large or highly compressed
# page and exhaust a worker's memory. The body is streamed and decoded incrementally under
# this ceiling. Sized well above a legitimate 100-row page of wide order rows.
MAX_RESPONSE_BYTES = 100 * 1024 * 1024
# Compressed bytes pulled per streamed read while enforcing the cap; small so a decompression
# bomb can inflate at most one chunk's worth past the cap before the read aborts.
RESPONSE_READ_CHUNK_BYTES = 64 * 1024

# Coarse backstop on rows fetched into one table in one sync run, far above any realistic
# store. Stops a host that keeps returning full pages forever from holding a resumable
# import until its activity timeout.
MAX_ROWS_PER_SYNC = 100_000_000


@frozen
class MedusaEndpointConfig:
    name: str
    # Path below the `/admin` prefix.
    path: str
    # Key the rows live under in Medusa's `{<key>: [...], "count": N, "offset": M, "limit": L}`
    # list envelope. Usually the snake_case resource name, but not always (`/admin/product-variants`
    # returns `variants`).
    data_selector: str
    # Server-side timestamp column used for the `[$gte]` filter and the ascending sort on
    # incremental runs. None means the list route documents no timestamp filters, so the
    # endpoint is full refresh only.
    incremental_field_name: str | None = "updated_at"

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        if self.incremental_field_name is None:
            return []
        return [incremental_field(self.incremental_field_name)]


# Medusa v2 Admin API list routes. Every entry is a documented list route on a stock v2 server;
# all carry `created_at`/`updated_at` operator filters except price lists, whose list route
# documents no timestamp filters. Fulfillments have no list route in v2, so they are absent.
MEDUSA_ENDPOINTS: dict[str, MedusaEndpointConfig] = {
    "Orders": MedusaEndpointConfig(name="Orders", path="/orders", data_selector="orders"),
    "DraftOrders": MedusaEndpointConfig(name="DraftOrders", path="/draft-orders", data_selector="draft_orders"),
    "Products": MedusaEndpointConfig(name="Products", path="/products", data_selector="products"),
    "ProductVariants": MedusaEndpointConfig(name="ProductVariants", path="/product-variants", data_selector="variants"),
    "Customers": MedusaEndpointConfig(name="Customers", path="/customers", data_selector="customers"),
    "CustomerGroups": MedusaEndpointConfig(
        name="CustomerGroups", path="/customer-groups", data_selector="customer_groups"
    ),
    "Regions": MedusaEndpointConfig(name="Regions", path="/regions", data_selector="regions"),
    "PriceLists": MedusaEndpointConfig(
        name="PriceLists", path="/price-lists", data_selector="price_lists", incremental_field_name=None
    ),
    "Returns": MedusaEndpointConfig(name="Returns", path="/returns", data_selector="returns"),
}

ENDPOINTS = tuple(MEDUSA_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MEDUSA_ENDPOINTS.items() if config.incremental_fields
}
