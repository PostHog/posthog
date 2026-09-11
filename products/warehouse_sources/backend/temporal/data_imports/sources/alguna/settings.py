from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Alguna list endpoints paginate with limit/offset.
PAGE_LIMIT = 100

# Every stream is full refresh. Alguna's list endpoints expose no created_at/updated_at server-side
# filters, and while /invoices supports issue/paid/due/invoicing date-range filters, the invoice
# *list* payload (InvoiceListItemResponse) doesn't include those date fields — so the pipeline
# can't track a watermark from synced rows. Billing data is low-cardinality, so full refresh is fine.


@dataclass(frozen=True)
class AlgunaQueryFanout:
    # Fan-out where the parent id rides a required *query* param on the child list endpoint (e.g.
    # /credit-notes?customer_id=...). The shared rest_source fan-out only binds resolve params in
    # the *path*, so these route through a hand-rolled iterator in alguna.py instead.
    parent_name: str
    query_param: str
    parent_field: str = "id"


@dataclass(frozen=True)
class AlgunaEndpointConfig:
    name: str
    path: str
    # Alguna requires `sort` (format "field:order") on most list endpoints; None for the endpoints
    # that don't accept it (payments, products, wallets, wallet-grants). All entities carry
    # created_at, and the API docs use it in sort examples, so it's the stable pagination order for
    # the endpoints that sort.
    sort: str | None = "created_at:asc"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: str = "created_at"
    # Whether the endpoint offset-paginates. False for a fan-out child that returns its whole
    # collection in one response (e.g. /subscriptions/{id}/versions).
    paginated: bool = True
    page_size: int = PAGE_LIMIT
    # Full refresh only — kept so the config satisfies the fan-out helper's protocol.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # Path-based fan-out driven by the shared rest_source helper (parent id in a {placeholder}).
    fanout: DependentEndpointConfig | None = None
    # Query-param fan-out driven by the hand-rolled iterator in alguna.py.
    query_fanout: AlgunaQueryFanout | None = None


ALGUNA_ENDPOINTS: dict[str, AlgunaEndpointConfig] = {
    "billable_metrics": AlgunaEndpointConfig(name="billable_metrics", path="/metrics"),
    "credit_notes": AlgunaEndpointConfig(
        name="credit_notes",
        path="/credit-notes",
        sort=None,
        # /credit-notes requires a customer_id query param, so list per customer.
        query_fanout=AlgunaQueryFanout(parent_name="customers", query_param="customer_id"),
    ),
    "customers": AlgunaEndpointConfig(name="customers", path="/customers"),
    "invoices": AlgunaEndpointConfig(name="invoices", path="/invoices"),
    "payments": AlgunaEndpointConfig(name="payments", path="/payments", sort=None),
    "plans": AlgunaEndpointConfig(name="plans", path="/plans"),
    "products": AlgunaEndpointConfig(name="products", path="/products", sort=None),
    "refunds": AlgunaEndpointConfig(name="refunds", path="/refunds"),
    "subscriptions": AlgunaEndpointConfig(name="subscriptions", path="/subscriptions"),
    "subscription_versions": AlgunaEndpointConfig(
        name="subscription_versions",
        path="/subscriptions/{subscription_id}/versions",
        sort=None,
        # Version id is unique within its subscription; scope it with the parent to be safe.
        primary_keys=["subscription_id", "id"],
        # The versions endpoint returns the whole list in one response — no limit/offset.
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="subscriptions",
            resolve_param="subscription_id",
            resolve_field="id",
            # The version payload already carries subscription_id; nothing to copy down.
            include_from_parent=[],
        ),
    ),
    "wallets": AlgunaEndpointConfig(name="wallets", path="/wallets", sort=None),
    "wallet_grants": AlgunaEndpointConfig(name="wallet_grants", path="/wallet-grants", sort=None),
}

ENDPOINTS = tuple(ALGUNA_ENDPOINTS.keys())

# Empty: no endpoint exposes an incremental watermark (see the note above), so every stream is full
# refresh. `build_endpoint_schemas` treats a missing entry — not an empty list — as non-incremental.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
