from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField

# Invoice Ninja defaults `per_page` to 20 and accepts larger values; 100 keeps request counts low
# without risking the larger-payload timeouts seen on very high page sizes.
DEFAULT_PAGE_SIZE = 100


@dataclass
class InvoiceNinjaEndpointConfig:
    name: str
    # Path appended to the API base (which already ends in `/api/v1`).
    path: str
    # Invoice Ninja index endpoints wrap their records under a top-level `data` key alongside a
    # `meta.pagination` object. The key is uniform across every list endpoint.
    primary_key: str = "id"
    page_size: int = DEFAULT_PAGE_SIZE
    should_sync_default: bool = True
    # Invoice Ninja documents server-side `created_at` / `updated_at` filters on its index endpoints,
    # but the timestamps it returns are integer unix seconds (not datetimes), and the ordering the API
    # applies when those filters are set could not be verified against the live API without a token.
    # An incremental cursor whose sort order we can't confirm risks a corrupted watermark on a mid-sync
    # shutdown, so every stream ships full-refresh only for now. Left empty deliberately — incremental
    # can be layered on per endpoint once the filter + sort behaviour is verified with real credentials.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Top-level index endpoints that return a full collection without requiring a parent resource id as a
# filter. Client and vendor contacts arrive embedded in their parent objects (Invoice Ninja nests a
# `contacts` array on each client/vendor), so they are captured without a dedicated fan-out endpoint.
INVOICENINJA_ENDPOINTS: dict[str, InvoiceNinjaEndpointConfig] = {
    "clients": InvoiceNinjaEndpointConfig(name="clients", path="/clients"),
    "credits": InvoiceNinjaEndpointConfig(name="credits", path="/credits"),
    "expense_categories": InvoiceNinjaEndpointConfig(name="expense_categories", path="/expense_categories"),
    "expenses": InvoiceNinjaEndpointConfig(name="expenses", path="/expenses"),
    "invoices": InvoiceNinjaEndpointConfig(name="invoices", path="/invoices"),
    "payments": InvoiceNinjaEndpointConfig(name="payments", path="/payments"),
    "payment_terms": InvoiceNinjaEndpointConfig(name="payment_terms", path="/payment_terms"),
    "products": InvoiceNinjaEndpointConfig(name="products", path="/products"),
    "projects": InvoiceNinjaEndpointConfig(name="projects", path="/projects"),
    "purchase_orders": InvoiceNinjaEndpointConfig(name="purchase_orders", path="/purchase_orders"),
    "quotes": InvoiceNinjaEndpointConfig(name="quotes", path="/quotes"),
    "recurring_invoices": InvoiceNinjaEndpointConfig(name="recurring_invoices", path="/recurring_invoices"),
    "tasks": InvoiceNinjaEndpointConfig(name="tasks", path="/tasks"),
    "tax_rates": InvoiceNinjaEndpointConfig(name="tax_rates", path="/tax_rates"),
    "vendors": InvoiceNinjaEndpointConfig(name="vendors", path="/vendors"),
}

ENDPOINTS = tuple(INVOICENINJA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INVOICENINJA_ENDPOINTS.items()
}
