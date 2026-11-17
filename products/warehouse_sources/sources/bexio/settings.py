from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

BEXIO_BASE_URL = "https://api.bexio.com"

# The 2.0 and 3.0 list endpoints page with `offset`/`limit` and cap `limit` at 2000.
OFFSET_PAGE_SIZE = 2000
# The 4.0 purchase endpoints page with `page`/`limit` and cap `limit` at 500.
PAGE_NUMBER_PAGE_SIZE = 500

UPDATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "updated_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@frozen
class BexioEndpointConfig:
    name: str
    path: str
    pagination: Literal["offset", "page"] = "offset"
    # The `order_by` value for a full refresh. None when the endpoint has no `order_by` parameter.
    order_by: Optional[str] = None
    # The POST search path that accepts an `updated_at` criterion. None means full refresh only.
    search_path: Optional[str] = None
    data_selector: Optional[str] = None
    partition_key: Optional[str] = None

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        return UPDATED_AT_INCREMENTAL_FIELDS if self.search_path else []


_ENDPOINT_LIST: tuple[BexioEndpointConfig, ...] = (
    BexioEndpointConfig(name="contacts", path="/2.0/contact", order_by="id", search_path="/2.0/contact/search"),
    BexioEndpointConfig(name="contact_groups", path="/2.0/contact_group", order_by="id"),
    BexioEndpointConfig(
        name="contact_relations",
        path="/2.0/contact_relation",
        order_by="id",
        search_path="/2.0/contact_relation/search",
    ),
    BexioEndpointConfig(name="invoices", path="/2.0/kb_invoice", order_by="id", search_path="/2.0/kb_invoice/search"),
    BexioEndpointConfig(name="quotes", path="/2.0/kb_offer", order_by="id", search_path="/2.0/kb_offer/search"),
    BexioEndpointConfig(name="orders", path="/2.0/kb_order", order_by="id", search_path="/2.0/kb_order/search"),
    BexioEndpointConfig(name="deliveries", path="/2.0/kb_delivery", order_by="id"),
    BexioEndpointConfig(name="purchase_orders", path="/3.0/purchase_orders", order_by="id"),
    BexioEndpointConfig(
        name="bills",
        path="/4.0/purchase/bills",
        pagination="page",
        data_selector="data",
        partition_key="created_at",
    ),
    BexioEndpointConfig(
        name="expenses",
        path="/4.0/expenses",
        pagination="page",
        data_selector="data",
        partition_key="created_at",
    ),
    BexioEndpointConfig(name="items", path="/2.0/article", order_by="id"),
    BexioEndpointConfig(name="projects", path="/2.0/pr_project", order_by="id"),
    BexioEndpointConfig(name="timesheets", path="/2.0/timesheet", order_by="id"),
    BexioEndpointConfig(name="tasks", path="/2.0/task", order_by="id"),
    BexioEndpointConfig(name="notes", path="/2.0/note"),
    BexioEndpointConfig(name="accounts", path="/2.0/accounts"),
    BexioEndpointConfig(name="account_groups", path="/2.0/account_groups"),
    BexioEndpointConfig(name="journal_entries", path="/3.0/accounting/journal"),
    BexioEndpointConfig(name="manual_entries", path="/3.0/accounting/manual_entries"),
    BexioEndpointConfig(name="business_years", path="/3.0/accounting/business_years"),
    BexioEndpointConfig(name="bank_accounts", path="/3.0/banking/accounts"),
    BexioEndpointConfig(name="currencies", path="/3.0/currencies"),
    BexioEndpointConfig(name="taxes", path="/3.0/taxes"),
    BexioEndpointConfig(name="users", path="/3.0/users"),
)

BEXIO_ENDPOINTS: dict[str, BexioEndpointConfig] = {endpoint.name: endpoint for endpoint in _ENDPOINT_LIST}

ENDPOINTS: tuple[str, ...] = tuple(BEXIO_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint.name: endpoint.incremental_fields for endpoint in _ENDPOINT_LIST if endpoint.incremental_fields
}
