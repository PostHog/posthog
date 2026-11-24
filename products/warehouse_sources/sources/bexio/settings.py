from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    frozen,
)

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
    pagination: Literal["offset", "page", "single"] = "offset"
    # The page-size parameter and the page-count path of a `page` endpoint.
    page_size_param: str = "limit"
    page_count_path: Optional[str] = "paging.page_count"
    # The `order_by` value for a full refresh. None when the endpoint has no `order_by` parameter.
    order_by: Optional[str] = None
    # The POST search path that accepts an `updated_at` criterion. None means full refresh only.
    search_path: Optional[str] = None
    data_selector: Optional[str] = None
    partition_key: Optional[str] = None
    primary_keys: tuple[str, ...] = ("id",)
    # Set for endpoints that need one request per parent row, such as the positions of one invoice.
    fanout: Optional[DependentEndpointConfig] = None

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        return UPDATED_AT_INCREMENTAL_FIELDS if self.search_path else []

    @property
    def default_incremental_field(self) -> Optional[str]:
        return None

    @property
    def page_size(self) -> int:
        return PAGE_NUMBER_PAGE_SIZE if self.pagination == "page" else OFFSET_PAGE_SIZE


def _invoice_children(name: str, path_suffix: str, pagination: Literal["offset", "single"]) -> BexioEndpointConfig:
    return BexioEndpointConfig(
        name=name,
        path=f"/2.0/kb_invoice/{{invoice_id}}/{path_suffix}",
        pagination=pagination,
        primary_keys=("invoice_id", "id"),
        fanout=DependentEndpointConfig(
            parent_name="invoices",
            resolve_param="invoice_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "invoice_id"},
            parent_params={"order_by": "id"},
        ),
    )


def _item_positions(name: str, parent_name: str, document_type: str, parent_key: str) -> BexioEndpointConfig:
    # Only item positions (`kb_position_article`) carry an article, a quantity and a price. The other
    # position types are text, subtotals, discounts and page breaks.
    return BexioEndpointConfig(
        name=name,
        path=f"/2.0/{document_type}/{{document_id}}/kb_position_article",
        primary_keys=(parent_key, "id"),
        fanout=DependentEndpointConfig(
            parent_name=parent_name,
            resolve_param="document_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": parent_key},
            parent_params={"order_by": "id"},
        ),
    )


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
    BexioEndpointConfig(name="client_services", path="/2.0/client_service", order_by="id"),
    BexioEndpointConfig(name="project_states", path="/2.0/pr_project_state", pagination="single"),
    BexioEndpointConfig(name="project_types", path="/2.0/pr_project_type", pagination="single", order_by="id"),
    _item_positions("invoice_item_positions", "invoices", "kb_invoice", "invoice_id"),
    _item_positions("quote_item_positions", "quotes", "kb_offer", "quote_id"),
    _item_positions("order_item_positions", "orders", "kb_order", "order_id"),
    BexioEndpointConfig(
        name="outgoing_payments",
        # The list takes one bill per request, through the required `bill_id` query parameter.
        path="/4.0/purchase/outgoing-payments?bill_id={bill_id}",
        pagination="page",
        data_selector="data",
        primary_keys=("bill_id", "id"),
        fanout=DependentEndpointConfig(
            parent_name="bills",
            resolve_param="bill_id",
            resolve_field="id",
            include_from_parent=[],
        ),
    ),
    _invoice_children("invoice_payments", "payment", "offset"),
    # The reminder list takes no paging parameters and returns every reminder of the invoice.
    _invoice_children("invoice_reminders", "kb_reminder", "single"),
    BexioEndpointConfig(
        name="bank_payments",
        path="/4.0/banking/payments",
        pagination="page",
        # This list names its page size `per-page`, wraps rows in `results` and gives a row count, not a page count.
        page_size_param="per-page",
        page_count_path=None,
        data_selector="results",
    ),
    # Lists only the active employees, in one response.
    BexioEndpointConfig(
        name="payroll_employees",
        path="/4.0/payroll/employees",
        pagination="single",
        data_selector="data",
    ),
)

BEXIO_ENDPOINTS: dict[str, BexioEndpointConfig] = {endpoint.name: endpoint for endpoint in _ENDPOINT_LIST}

ENDPOINTS: tuple[str, ...] = tuple(BEXIO_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint.name: endpoint.incremental_fields for endpoint in _ENDPOINT_LIST if endpoint.incremental_fields
}
