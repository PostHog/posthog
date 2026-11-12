from datetime import timedelta

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

API_VERSION = "v2"
API_BASE_URL = f"https://app.pennylane.com/api/external/{API_VERSION}"
API_DOCS_URL = "https://pennylane.readme.io/docs/stay-updated-with-our-api-changes"

PAGE_SIZE = 100
# One changelog page names at most this many records, so one `id in` request fetches all of them.
CHANGELOG_PAGE_SIZE = PAGE_SIZE
# Pennylane keeps changelog events for 4 weeks and answers 422 to an older `start_date`. A watermark
# older than this window cannot be read from the changelog, so the run lists the whole table again.
CHANGELOG_WINDOW = timedelta(days=27)
# Start the changelog read a little before the watermark. A row's `updated_at` and the changelog's
# `processed_at` come from different clocks, and merge removes the rows that are read twice.
CHANGELOG_OVERLAP = timedelta(minutes=10)


@frozen
class PennylaneEndpointConfig:
    path: str
    # The read-only token scope the endpoint needs. Every endpoint also accepts the `:all` scope.
    scope: str
    partition_key: str | None = "created_at"
    # Changelog of inserts, updates and deletes. Only endpoints with one support incremental sync,
    # because no list endpoint can filter on `updated_at`.
    changelog_path: str | None = None
    # Endpoints that document a `sort` parameter. The list is sorted by ascending `id` so that rows
    # created during the walk land at its end.
    sortable: bool = True
    page_size: int = PAGE_SIZE


ENDPOINTS: dict[str, PennylaneEndpointConfig] = {
    "customers": PennylaneEndpointConfig(
        path="/customers", scope="customers:readonly", changelog_path="/changelogs/customers"
    ),
    "suppliers": PennylaneEndpointConfig(
        path="/suppliers", scope="suppliers:readonly", changelog_path="/changelogs/suppliers"
    ),
    "products": PennylaneEndpointConfig(
        path="/products", scope="products:readonly", changelog_path="/changelogs/products"
    ),
    "customer_invoices": PennylaneEndpointConfig(
        path="/customer_invoices",
        scope="customer_invoices:readonly",
        changelog_path="/changelogs/customer_invoices",
    ),
    "supplier_invoices": PennylaneEndpointConfig(
        path="/supplier_invoices",
        scope="supplier_invoices:readonly",
        changelog_path="/changelogs/supplier_invoices",
    ),
    "quotes": PennylaneEndpointConfig(path="/quotes", scope="quotes:readonly", changelog_path="/changelogs/quotes"),
    "commercial_documents": PennylaneEndpointConfig(
        path="/commercial_documents", scope="commercial_documents:readonly"
    ),
    "billing_subscriptions": PennylaneEndpointConfig(
        path="/billing_subscriptions", scope="billing_subscriptions:readonly"
    ),
    "purchase_requests": PennylaneEndpointConfig(path="/purchase_requests", scope="purchase_requests:readonly"),
    "transactions": PennylaneEndpointConfig(
        path="/transactions", scope="transactions:readonly", changelog_path="/changelogs/transactions"
    ),
    "bank_accounts": PennylaneEndpointConfig(path="/bank_accounts", scope="bank_accounts:readonly"),
    "journals": PennylaneEndpointConfig(path="/journals", scope="journals:readonly", partition_key=None),
    "ledger_accounts": PennylaneEndpointConfig(
        path="/ledger_accounts", scope="ledger_accounts:readonly", page_size=1000
    ),
    "ledger_entries": PennylaneEndpointConfig(
        path="/ledger_entries", scope="ledger_entries:readonly", changelog_path="/changelogs/ledger_entries"
    ),
    "ledger_entry_lines": PennylaneEndpointConfig(
        path="/ledger_entry_lines",
        scope="ledger_entries:readonly",
        changelog_path="/changelogs/ledger_entry_lines",
    ),
    "fiscal_years": PennylaneEndpointConfig(path="/fiscal_years", scope="fiscal_years:readonly"),
    "categories": PennylaneEndpointConfig(path="/categories", scope="categories:readonly"),
    "category_groups": PennylaneEndpointConfig(path="/category_groups", scope="categories:readonly", sortable=False),
}

_UPDATED_AT: IncrementalField = {
    "label": "updated_at",
    "type": IncrementalFieldType.DateTime,
    "field": "updated_at",
    "field_type": IncrementalFieldType.DateTime,
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [_UPDATED_AT] for name, config in ENDPOINTS.items() if config.changelog_path is not None
}

AUTH_ERROR = (
    "Pennylane rejected your API token. The token can be wrong, expired or deleted. "
    "Generate a new token in Pennylane under Settings > Connectivity > Developers, then reconnect the source."
)

FORBIDDEN_ERROR = (
    "Pennylane refused access for this API token. "
    "Check that your Pennylane plan includes API access and that the token is still active, then reconnect the source."
)


def scope_error(endpoint: str) -> str:
    return (
        f"Your Pennylane API token can't read {endpoint.replace('_', ' ')}. "
        f"Generate a token with the `{ENDPOINTS[endpoint].scope}` scope, then reconnect the source."
    )


NON_RETRYABLE_ERRORS: dict[str, str | None] = {
    f"401 Client Error: Unauthorized for url: {API_BASE_URL}": AUTH_ERROR,
    f"403 Client Error: Forbidden for url: {API_BASE_URL}": (
        "Your Pennylane API token doesn't have the scope for one of the tables you sync. "
        "Generate a token with read access to that data, then reconnect the source."
    ),
}
