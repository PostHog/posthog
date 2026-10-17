from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

XERO_API_BASE_URL = "https://api.xero.com/api.xro/2.0"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"

PAGE_SIZE = 1000

UPDATED_DATE_FIELD = "UpdatedDateUTC"


@dataclass(frozen=True)
class XeroEndpointConfig:
    name: str
    path: str
    data_key: str
    primary_key: str
    paginated: bool = True
    incremental: bool = True
    extra_params: dict[str, str] = field(default_factory=dict)


# Journals are left out because Xero gates them behind its paid Advanced API tier. No table is
# partitioned, because Xero records carry no creation timestamp.
XERO_ENDPOINTS: dict[str, XeroEndpointConfig] = {
    "invoices": XeroEndpointConfig(
        name="invoices",
        path="/Invoices",
        data_key="Invoices",
        primary_key="InvoiceID",
        extra_params={"includeArchived": "true"},
    ),
    "credit_notes": XeroEndpointConfig(
        name="credit_notes", path="/CreditNotes", data_key="CreditNotes", primary_key="CreditNoteID"
    ),
    "payments": XeroEndpointConfig(name="payments", path="/Payments", data_key="Payments", primary_key="PaymentID"),
    "bank_transactions": XeroEndpointConfig(
        name="bank_transactions",
        path="/BankTransactions",
        data_key="BankTransactions",
        primary_key="BankTransactionID",
    ),
    "contacts": XeroEndpointConfig(
        name="contacts",
        path="/Contacts",
        data_key="Contacts",
        primary_key="ContactID",
        extra_params={"includeArchived": "true"},
    ),
    "manual_journals": XeroEndpointConfig(
        name="manual_journals", path="/ManualJournals", data_key="ManualJournals", primary_key="ManualJournalID"
    ),
    "overpayments": XeroEndpointConfig(
        name="overpayments", path="/Overpayments", data_key="Overpayments", primary_key="OverpaymentID"
    ),
    "prepayments": XeroEndpointConfig(
        name="prepayments", path="/Prepayments", data_key="Prepayments", primary_key="PrepaymentID"
    ),
    "purchase_orders": XeroEndpointConfig(
        name="purchase_orders", path="/PurchaseOrders", data_key="PurchaseOrders", primary_key="PurchaseOrderID"
    ),
    "accounts": XeroEndpointConfig(
        name="accounts", path="/Accounts", data_key="Accounts", primary_key="AccountID", paginated=False
    ),
    "items": XeroEndpointConfig(name="items", path="/Items", data_key="Items", primary_key="ItemID", paginated=False),
    "organisation": XeroEndpointConfig(
        name="organisation",
        path="/Organisation",
        data_key="Organisations",
        primary_key="OrganisationID",
        paginated=False,
        incremental=False,
    ),
}

ENDPOINTS = tuple(XERO_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": UPDATED_DATE_FIELD,
            "type": IncrementalFieldType.DateTime,
            "field": UPDATED_DATE_FIELD,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for name, config in XERO_ENDPOINTS.items()
    if config.incremental
}
