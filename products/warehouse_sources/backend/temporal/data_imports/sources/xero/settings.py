from dataclasses import dataclass
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How the Accounting API walks a collection:
#   "page"   — `?page=N` (Invoices, Contacts, ...); ask for pages until one comes back empty
#   "offset" — `?offset=<last JournalNumber>` (Journals only)
#   "single" — the whole collection arrives in one response (Accounts, Users, ...)
PaginationMode = Literal["page", "offset", "single"]

# Column we stamp onto every row with the Xero organisation the row came from. A Xero login can
# reach several organisations, so it is part of every primary key.
TENANT_ID_COLUMN = "_tenant_id"
TENANT_NAME_COLUMN = "_tenant_name"


@dataclass(frozen=True)
class XeroEndpointConfig:
    name: str
    """Table name we expose to the user (snake_case)."""
    path: str
    """Accounting API resource path, e.g. ``Invoices`` (called as GET ``/api.xro/2.0/Invoices``)."""
    data_key: str
    """Key holding the row array in Xero's JSON envelope. Usually the plural of ``path``, but
    ``GET /Organisation`` answers with ``Organisations``."""
    primary_key: list[str]
    """Resource-level key. ``TENANT_ID_COLUMN`` is prepended when the response is built."""
    pagination: PaginationMode = "single"
    incremental_field: Optional[str] = None
    """Timestamp the ``If-Modified-Since`` request header filters on, when the resource has one.

    Xero applies the header to whichever timestamp the resource tracks changes with, so this is
    also the field we advertise as the incremental cursor.
    """
    partition_key: Optional[str] = None
    """A STABLE creation-time field to partition on. ``None`` disables partitioning — only
    Journals exposes a creation timestamp that never moves."""


XERO_ENDPOINTS: dict[str, XeroEndpointConfig] = {
    "accounts": XeroEndpointConfig(
        name="accounts",
        path="Accounts",
        data_key="Accounts",
        primary_key=["AccountID"],
        incremental_field="UpdatedDateUTC",
    ),
    "bank_transactions": XeroEndpointConfig(
        name="bank_transactions",
        path="BankTransactions",
        data_key="BankTransactions",
        primary_key=["BankTransactionID"],
        pagination="page",
        incremental_field="UpdatedDateUTC",
    ),
    "bank_transfers": XeroEndpointConfig(
        name="bank_transfers",
        path="BankTransfers",
        data_key="BankTransfers",
        primary_key=["BankTransferID"],
        # Transfers are the one non-journal resource with no UpdatedDateUTC; they are not
        # editable after creation, so the creation timestamp is both cursor and partition key.
        incremental_field="CreatedDateUTC",
        partition_key="CreatedDateUTC",
    ),
    "batch_payments": XeroEndpointConfig(
        name="batch_payments",
        path="BatchPayments",
        data_key="BatchPayments",
        primary_key=["BatchPaymentID"],
        incremental_field="UpdatedDateUTC",
    ),
    "branding_themes": XeroEndpointConfig(
        name="branding_themes",
        path="BrandingThemes",
        data_key="BrandingThemes",
        primary_key=["BrandingThemeID"],
    ),
    "contact_groups": XeroEndpointConfig(
        name="contact_groups",
        path="ContactGroups",
        data_key="ContactGroups",
        primary_key=["ContactGroupID"],
    ),
    "contacts": XeroEndpointConfig(
        name="contacts",
        path="Contacts",
        data_key="Contacts",
        primary_key=["ContactID"],
        pagination="page",
        incremental_field="UpdatedDateUTC",
    ),
    "credit_notes": XeroEndpointConfig(
        name="credit_notes",
        path="CreditNotes",
        data_key="CreditNotes",
        primary_key=["CreditNoteID"],
        pagination="page",
        incremental_field="UpdatedDateUTC",
    ),
    "currencies": XeroEndpointConfig(
        name="currencies",
        path="Currencies",
        data_key="Currencies",
        primary_key=["Code"],
    ),
    "employees": XeroEndpointConfig(
        name="employees",
        path="Employees",
        data_key="Employees",
        primary_key=["EmployeeID"],
        incremental_field="UpdatedDateUTC",
    ),
    "expense_claims": XeroEndpointConfig(
        name="expense_claims",
        path="ExpenseClaims",
        data_key="ExpenseClaims",
        primary_key=["ExpenseClaimID"],
        incremental_field="UpdatedDateUTC",
    ),
    "invoices": XeroEndpointConfig(
        name="invoices",
        path="Invoices",
        data_key="Invoices",
        primary_key=["InvoiceID"],
        pagination="page",
        incremental_field="UpdatedDateUTC",
    ),
    "items": XeroEndpointConfig(
        name="items",
        path="Items",
        data_key="Items",
        primary_key=["ItemID"],
        incremental_field="UpdatedDateUTC",
    ),
    "journals": XeroEndpointConfig(
        name="journals",
        path="Journals",
        data_key="Journals",
        primary_key=["JournalID"],
        pagination="offset",
        # Journals are immutable once posted, so their creation timestamp is both the change
        # cursor and a partition key that never rewrites.
        incremental_field="CreatedDateUTC",
        partition_key="CreatedDateUTC",
    ),
    "linked_transactions": XeroEndpointConfig(
        name="linked_transactions",
        path="LinkedTransactions",
        data_key="LinkedTransactions",
        primary_key=["LinkedTransactionID"],
        pagination="page",
        incremental_field="UpdatedDateUTC",
    ),
    "manual_journals": XeroEndpointConfig(
        name="manual_journals",
        path="ManualJournals",
        data_key="ManualJournals",
        primary_key=["ManualJournalID"],
        pagination="page",
        incremental_field="UpdatedDateUTC",
    ),
    "organisations": XeroEndpointConfig(
        name="organisations",
        path="Organisation",
        data_key="Organisations",
        primary_key=["OrganisationID"],
    ),
    "overpayments": XeroEndpointConfig(
        name="overpayments",
        path="Overpayments",
        data_key="Overpayments",
        primary_key=["OverpaymentID"],
        pagination="page",
        incremental_field="UpdatedDateUTC",
    ),
    "payments": XeroEndpointConfig(
        name="payments",
        path="Payments",
        data_key="Payments",
        primary_key=["PaymentID"],
        pagination="page",
        incremental_field="UpdatedDateUTC",
    ),
    "prepayments": XeroEndpointConfig(
        name="prepayments",
        path="Prepayments",
        data_key="Prepayments",
        primary_key=["PrepaymentID"],
        pagination="page",
        incremental_field="UpdatedDateUTC",
    ),
    "purchase_orders": XeroEndpointConfig(
        name="purchase_orders",
        path="PurchaseOrders",
        data_key="PurchaseOrders",
        primary_key=["PurchaseOrderID"],
        pagination="page",
        incremental_field="UpdatedDateUTC",
    ),
    "quotes": XeroEndpointConfig(
        name="quotes",
        path="Quotes",
        data_key="Quotes",
        primary_key=["QuoteID"],
        pagination="page",
        incremental_field="UpdatedDateUTC",
    ),
    "receipts": XeroEndpointConfig(
        name="receipts",
        path="Receipts",
        data_key="Receipts",
        primary_key=["ReceiptID"],
        incremental_field="UpdatedDateUTC",
    ),
    "repeating_invoices": XeroEndpointConfig(
        name="repeating_invoices",
        path="RepeatingInvoices",
        data_key="RepeatingInvoices",
        primary_key=["RepeatingInvoiceID"],
    ),
    "tax_rates": XeroEndpointConfig(
        name="tax_rates",
        path="TaxRates",
        data_key="TaxRates",
        # Tax rates have no surrogate id; TaxType is the code Xero references them by.
        primary_key=["TaxType"],
    ),
    "tracking_categories": XeroEndpointConfig(
        name="tracking_categories",
        path="TrackingCategories",
        data_key="TrackingCategories",
        primary_key=["TrackingCategoryID"],
    ),
    "users": XeroEndpointConfig(
        name="users",
        path="Users",
        data_key="Users",
        primary_key=["UserID"],
        incremental_field="UpdatedDateUTC",
    ),
}

ENDPOINTS = tuple(XERO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field(config.incremental_field, IncrementalFieldType.DateTime)]
    for name, config in XERO_ENDPOINTS.items()
    if config.incremental_field is not None
}
