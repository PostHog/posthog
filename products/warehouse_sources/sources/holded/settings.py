from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField

HOLDED_API_HOST = "https://api.holded.com"

# Endpoints that page document their maximum `limit`. Most allow 200, a few cap at 100, and the
# pagination guide gives 100 as the maximum for the endpoints that do not state one.
MAX_PAGE_SIZE = 200
SMALL_PAGE_SIZE = 100

# Ledger entries and time off requests require a date range. The API documents no maximum span, so
# one wide range reads every row in one cursor walk.
FULL_RANGE_START_DATE = "1970-01-01"
FULL_RANGE_END_DATE = "2099-12-31"


@dataclass(frozen=True)
class HoldedEndpointConfig:
    path: str
    # None means the endpoint returns every row in one response and accepts no cursor.
    page_size: Optional[int] = MAX_PAGE_SIZE
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # A field that does not change after the row is created. Documents use their issue date.
    partition_key: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)
    # Set for an endpoint whose path holds the id of a row from another endpoint.
    fanout: Optional[DependentEndpointConfig] = None


def _document(path: str) -> HoldedEndpointConfig:
    return HoldedEndpointConfig(path=path, partition_key="date")


HOLDED_ENDPOINTS: dict[str, HoldedEndpointConfig] = {
    # Sales documents
    "invoices": _document("/invoices"),
    "credit_notes": _document("/credit-notes"),
    "sales_receipts": _document("/sales-receipts"),
    "estimates": _document("/estimates"),
    "proformas": _document("/proformas"),
    "sales_orders": _document("/sales-orders"),
    "waybills": _document("/waybills"),
    "receipt_notes": _document("/receipt-notes"),
    # Purchase documents
    "purchases": _document("/purchases"),
    "purchase_refunds": _document("/purchase-refunds"),
    "purchase_orders": _document("/purchase-orders"),
    "purchase_shipments": _document("/purchase-shipments"),
    "payments": HoldedEndpointConfig(path="/payments", page_size=SMALL_PAGE_SIZE, partition_key="date"),
    # Templates that generate invoices on a schedule. The API publishes no row shape, so no partition.
    "recurring_invoices": HoldedEndpointConfig(path="/recurring-invoices"),
    # Catalog and contacts
    "contacts": HoldedEndpointConfig(path="/contacts", page_size=SMALL_PAGE_SIZE, partition_key="created_at"),
    "contact_groups": HoldedEndpointConfig(path="/contact-groups", page_size=SMALL_PAGE_SIZE),
    "products": HoldedEndpointConfig(path="/products"),
    "services": HoldedEndpointConfig(path="/services", page_size=SMALL_PAGE_SIZE, params={"include_archived": "true"}),
    "warehouses": HoldedEndpointConfig(path="/warehouses", page_size=None),
    "production_orders": HoldedEndpointConfig(path="/production-orders", partition_key="date"),
    # Accounting and treasury
    "ledger_entries": HoldedEndpointConfig(
        path="/ledger-entries",
        # One ledger entry has one row per line, and each row repeats the entry id.
        primary_keys=["id", "line"],
        partition_key="date",
        params={"start_date": FULL_RANGE_START_DATE, "end_date": FULL_RANGE_END_DATE},
    ),
    "accounting_accounts": HoldedEndpointConfig(
        path="/accounting-accounts",
        page_size=None,
        params={"archived": "true", "include_empty": "true"},
    ),
    "taxes": HoldedEndpointConfig(path="/taxes", page_size=None),
    "treasury_accounts": HoldedEndpointConfig(path="/treasury/accounts", page_size=SMALL_PAGE_SIZE),
    # Raw bank statement entries. Cash-type accounts answer with an empty list.
    "bank_movements": HoldedEndpointConfig(
        path="/treasury/accounts/{account_id}/bank-movements",
        primary_keys=["treasury_account_id", "id"],
        partition_key="booking_date",
        fanout=DependentEndpointConfig(
            parent_name="treasury_accounts",
            resolve_param="account_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "treasury_account_id"},
        ),
    ),
    "payment_methods": HoldedEndpointConfig(path="/payment-methods"),
    # CRM
    "funnels": HoldedEndpointConfig(path="/funnels", page_size=SMALL_PAGE_SIZE, partition_key="created_at"),
    "leads": HoldedEndpointConfig(path="/leads", page_size=SMALL_PAGE_SIZE, partition_key="created_at"),
    "events": HoldedEndpointConfig(path="/events", page_size=SMALL_PAGE_SIZE, partition_key="created_at"),
    # Projects
    "projects": HoldedEndpointConfig(path="/projects", page_size=SMALL_PAGE_SIZE),
    "tasks": HoldedEndpointConfig(path="/tasks", page_size=SMALL_PAGE_SIZE, partition_key="created_at"),
    "project_times": HoldedEndpointConfig(path="/project-times", page_size=SMALL_PAGE_SIZE),
    # Team
    "employees": HoldedEndpointConfig(path="/employees", page_size=SMALL_PAGE_SIZE),
    "employee_times": HoldedEndpointConfig(path="/employee-times", page_size=SMALL_PAGE_SIZE),
    "employee_time_offs": HoldedEndpointConfig(
        path="/employees/time-offs",
        page_size=SMALL_PAGE_SIZE,
        partition_key="start_date",
        params={"start_date_from": FULL_RANGE_START_DATE, "start_date_to": FULL_RANGE_END_DATE},
    ),
}

ENDPOINTS = tuple(HOLDED_ENDPOINTS)

# No list endpoint filters on a modification time. The document date filters match the issue date,
# which does not move when a document is paid or edited, so every table is full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
