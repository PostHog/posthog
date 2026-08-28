from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Dodo Payments serves test and live data from two entirely separate hosts, each with its own
# API key. A key issued for one mode is rejected by the other, so the mode is an explicit source
# field rather than something we can infer from the key.
MODE_HOSTS = {
    "live": "https://live.dodopayments.com",
    "test": "https://test.dodopayments.com",
}
DEFAULT_MODE = "live"

# Every list endpoint caps `page_size` at 100 (the default is 10).
PAGE_SIZE = 100

# `(connect, read)` seconds. Bounds every REST request so a stalled connect or a hung read cannot
# pin an import worker indefinitely; the read budget is generous because a slow page is still worth
# waiting for against the 240 requests/minute rate limit.
REQUEST_TIMEOUT_SECONDS: tuple[float, float] = (10.0, 60.0)

# Rows whose fields get restated after creation re-read a trailing 30 day window on every
# incremental run. Dodo only filters on `created_at` - there is no updated-since filter anywhere
# in the API - so a bare creation cursor would freeze `status`, `dispute_status` and
# `refund_status` at whatever they were when the row was first imported. Users can change the
# window per table in the schema settings.
RESTATED_LOOKBACK_SECONDS = 30 * 24 * 60 * 60


@dataclass(frozen=True)
class DodoPaymentsEndpointConfig:
    path: str
    primary_keys: list[str]
    # Query param carrying the server-side "created on or after" filter, when the endpoint has
    # one. `None` means the endpoint offers no date filter at all and must be full-refreshed.
    start_param: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation timestamp used for datetime partitioning. `None` where the resource has no
    # creation timestamp at all (brands).
    partition_key: str | None = "created_at"
    # `/brands` is the one list endpoint that takes no query parameters, so it is a single page.
    paginated: bool = True
    # Fields on these resources are restated in place after creation, so incremental runs need
    # the trailing re-read window above.
    restated: bool = False


DODOPAYMENTS_ENDPOINTS: dict[str, DodoPaymentsEndpointConfig] = {
    "payments": DodoPaymentsEndpointConfig(
        path="/payments",
        primary_keys=["payment_id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
        restated=True,
    ),
    "subscriptions": DodoPaymentsEndpointConfig(
        path="/subscriptions",
        primary_keys=["subscription_id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
        restated=True,
    ),
    "customers": DodoPaymentsEndpointConfig(
        path="/customers",
        primary_keys=["customer_id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
        restated=True,
    ),
    "refunds": DodoPaymentsEndpointConfig(
        path="/refunds",
        primary_keys=["refund_id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
        restated=True,
    ),
    "disputes": DodoPaymentsEndpointConfig(
        path="/disputes",
        primary_keys=["dispute_id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
        restated=True,
    ),
    "payouts": DodoPaymentsEndpointConfig(
        path="/payouts",
        primary_keys=["payout_id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
        restated=True,
    ),
    "license_keys": DodoPaymentsEndpointConfig(
        path="/license_keys",
        primary_keys=["id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
        restated=True,
    ),
    "balance_ledger_entries": DodoPaymentsEndpointConfig(
        path="/balances/ledger",
        primary_keys=["id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
    ),
    # Usage-billing events are immutable once ingested, and the filter param is `start`, not
    # `created_at_gte`.
    "events": DodoPaymentsEndpointConfig(
        path="/events",
        primary_keys=["event_id"],
        start_param="start",
        incremental_fields=[incremental_field("timestamp")],
        partition_key="timestamp",
    ),
    # Catalog resources: no date filter of any kind, so full refresh only.
    "products": DodoPaymentsEndpointConfig(path="/products", primary_keys=["product_id"]),
    "product_collections": DodoPaymentsEndpointConfig(path="/product-collections", primary_keys=["id"]),
    "discounts": DodoPaymentsEndpointConfig(path="/discounts", primary_keys=["discount_id"]),
    "addons": DodoPaymentsEndpointConfig(path="/addons", primary_keys=["id"]),
    "brands": DodoPaymentsEndpointConfig(
        path="/brands",
        primary_keys=["brand_id"],
        partition_key=None,
        paginated=False,
    ),
    "meters": DodoPaymentsEndpointConfig(path="/meters", primary_keys=["id"]),
    "license_key_instances": DodoPaymentsEndpointConfig(path="/license_key_instances", primary_keys=["id"]),
    "entitlements": DodoPaymentsEndpointConfig(path="/entitlements", primary_keys=["id"]),
    "credit_entitlements": DodoPaymentsEndpointConfig(path="/credit-entitlements", primary_keys=["id"]),
}

ENDPOINTS = tuple(DODOPAYMENTS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DODOPAYMENTS_ENDPOINTS.items() if config.incremental_fields
}

INCREMENTAL_ENDPOINTS = tuple(INCREMENTAL_FIELDS.keys())
