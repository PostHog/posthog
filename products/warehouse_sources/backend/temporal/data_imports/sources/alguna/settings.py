from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField

# Every stream is full refresh. Alguna's list endpoints expose no created_at/updated_at server-side
# filters, and while /invoices supports issue/paid/due/invoicing date-range filters, the invoice
# *list* payload (InvoiceListItemResponse) doesn't include those date fields — so the pipeline
# can't track a watermark from synced rows. Billing data is low-cardinality, so full refresh is fine.


@dataclass
class AlgunaEndpointConfig:
    name: str
    path: str
    # Alguna requires `sort` (format "field:order") on most list endpoints; None for the endpoints
    # that don't accept it (payments, products). All entities carry created_at, and the API docs use
    # it in sort examples, so it's the stable pagination order for the endpoints that sort.
    sort: str | None = "created_at:asc"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: str = "created_at"


ALGUNA_ENDPOINTS: dict[str, AlgunaEndpointConfig] = {
    "billable_metrics": AlgunaEndpointConfig(name="billable_metrics", path="/metrics"),
    "customers": AlgunaEndpointConfig(name="customers", path="/customers"),
    "invoices": AlgunaEndpointConfig(name="invoices", path="/invoices"),
    "payments": AlgunaEndpointConfig(name="payments", path="/payments", sort=None),
    "plans": AlgunaEndpointConfig(name="plans", path="/plans"),
    "products": AlgunaEndpointConfig(name="products", path="/products", sort=None),
    "refunds": AlgunaEndpointConfig(name="refunds", path="/refunds"),
    "subscriptions": AlgunaEndpointConfig(name="subscriptions", path="/subscriptions"),
}

ENDPOINTS = tuple(ALGUNA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ALGUNA_ENDPOINTS}
