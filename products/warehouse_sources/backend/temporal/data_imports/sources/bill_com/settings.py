from dataclasses import dataclass

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# BILL v3 list endpoints, taken from the published OpenAPI description
# (https://developer.bill.com/openapi/bill-v3-api.json). Every one of them shares the same
# response envelope (`{"results": [...], "nextPage": ..., "prevPage": ...}`), the same
# `max`/`page`/`sort`/`filters` query params, and returns objects carrying `id`, `createdTime`,
# and `updatedTime`.
#
# The `/v3/spend/*` resources are deliberately excluded: BILL Spend & Expense is a separate API
# surface authenticated with its own API token rather than the session login used here.

CREATED_TIME_FIELD = "createdTime"
UPDATED_TIME_FIELD = "updatedTime"


@dataclass(frozen=True)
class BillComEndpointConfig:
    name: str
    path: str


def _endpoint(name: str, path: str) -> BillComEndpointConfig:
    return BillComEndpointConfig(name=name, path=path)


BILL_COM_ENDPOINTS: dict[str, BillComEndpointConfig] = {
    # Accounts payable
    "bills": _endpoint("bills", "/bills"),
    "payments": _endpoint("payments", "/payments"),
    "vendors": _endpoint("vendors", "/vendors"),
    "vendor_credits": _endpoint("vendor_credits", "/vendor-credits"),
    "recurring_bills": _endpoint("recurring_bills", "/recurringbills"),
    # Accounts receivable
    "invoices": _endpoint("invoices", "/invoices"),
    "customers": _endpoint("customers", "/customers"),
    "receivable_payments": _endpoint("receivable_payments", "/receivable-payments"),
    "credit_memos": _endpoint("credit_memos", "/credit-memos"),
    "recurring_invoices": _endpoint("recurring_invoices", "/recurring-invoices"),
    # Organization, funding, and accounting classifications
    "bank_accounts": _endpoint("bank_accounts", "/funding-accounts/banks"),
    "chart_of_accounts": _endpoint("chart_of_accounts", "/classifications/chart-of-accounts"),
    "accounting_classes": _endpoint("accounting_classes", "/classifications/accounting-classes"),
    "departments": _endpoint("departments", "/classifications/departments"),
    "employees": _endpoint("employees", "/classifications/employees"),
    "items": _endpoint("items", "/classifications/items"),
    "jobs": _endpoint("jobs", "/classifications/jobs"),
    "locations": _endpoint("locations", "/classifications/locations"),
    "users": _endpoint("users", "/users"),
}

ENDPOINTS: tuple[str, ...] = tuple(BILL_COM_ENDPOINTS.keys())

# `filters=updatedTime:gte:<value>` is a real server-side filter on every list endpoint, so all
# endpoints sync incrementally. `updatedTime` is listed first so it becomes the default cursor —
# it catches edits to older records that `createdTime` would miss.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field(UPDATED_TIME_FIELD), incremental_field(CREATED_TIME_FIELD)] for name in ENDPOINTS
}
