from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Every Business Central API v2.0 entity except `companies` lives under a company, so the whole
# catalog below is company-scoped fan-out with `companies` as the parent.
COMPANIES_ENDPOINT = "companies"

# Business Central stamps a `lastModifiedDateTime` on master data and documents; it is the only
# server-side filterable change marker the standard API exposes.
LAST_MODIFIED_FIELD = "lastModifiedDateTime"


@dataclass(frozen=True)
class BusinessCentralEndpoint:
    """One Business Central API v2.0 entity set.

    `name` doubles as the OData entity-set segment and the schema/table name, which is how the
    standard API is documented (`/companies({id})/salesInvoices`).
    """

    name: str
    # False only for `companies`, which is the fan-out parent and is not itself nested.
    company_scoped: bool = True
    primary_keys: tuple[str, ...] = ("company_id", "id")
    # Field used for the `$filter ... gt` incremental window. None means full refresh.
    cursor_field: Optional[str] = None
    # Stable posting/document date used for datetime partitioning. Never `lastModifiedDateTime`,
    # which moves on every edit and would rewrite partitions each sync.
    partition_key: Optional[str] = None

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        return [incremental_field(self.cursor_field)] if self.cursor_field else []


def _document(name: str, partition_key: str = "postingDate") -> BusinessCentralEndpoint:
    return BusinessCentralEndpoint(name=name, cursor_field=LAST_MODIFIED_FIELD, partition_key=partition_key)


def _document_lines(name: str) -> BusinessCentralEndpoint:
    # Line entities carry no change marker of their own, so they full-refresh. `id` is a systemId
    # GUID but the documented key is (documentId, sequence) — use it, plus the company.
    return BusinessCentralEndpoint(name=name, primary_keys=("company_id", "documentId", "sequence"))


def _master(name: str) -> BusinessCentralEndpoint:
    return BusinessCentralEndpoint(name=name, cursor_field=LAST_MODIFIED_FIELD)


BUSINESS_CENTRAL_ENDPOINTS: dict[str, BusinessCentralEndpoint] = {
    COMPANIES_ENDPOINT: BusinessCentralEndpoint(
        name=COMPANIES_ENDPOINT,
        company_scoped=False,
        primary_keys=("id",),
    ),
    # Master data / setup tables.
    "accounts": _master("accounts"),
    "bankAccounts": _master("bankAccounts"),
    "currencies": _master("currencies"),
    "customers": _master("customers"),
    "dimensions": _master("dimensions"),
    "dimensionValues": _master("dimensionValues"),
    "employees": _master("employees"),
    "itemCategories": _master("itemCategories"),
    "items": _master("items"),
    "paymentMethods": _master("paymentMethods"),
    "paymentTerms": _master("paymentTerms"),
    "shipmentMethods": _master("shipmentMethods"),
    "unitsOfMeasure": _master("unitsOfMeasure"),
    "vendors": _master("vendors"),
    # `locations` has no documented lastModifiedDateTime, so it full-refreshes.
    "locations": BusinessCentralEndpoint(name="locations"),
    # Documents and their lines.
    "salesInvoices": _document("salesInvoices"),
    "salesInvoiceLines": _document_lines("salesInvoiceLines"),
    "salesOrders": _document("salesOrders"),
    "salesOrderLines": _document_lines("salesOrderLines"),
    "salesQuotes": _document("salesQuotes", partition_key="documentDate"),
    "salesQuoteLines": _document_lines("salesQuoteLines"),
    "salesCreditMemos": _document("salesCreditMemos"),
    "salesCreditMemoLines": _document_lines("salesCreditMemoLines"),
    "purchaseInvoices": _document("purchaseInvoices"),
    "purchaseInvoiceLines": _document_lines("purchaseInvoiceLines"),
    # Ledger / payment entries.
    "generalLedgerEntries": BusinessCentralEndpoint(
        name="generalLedgerEntries",
        primary_keys=("company_id", "entryNumber"),
        cursor_field=LAST_MODIFIED_FIELD,
        partition_key="postingDate",
    ),
    "customerPayments": _document("customerPayments"),
}

ENDPOINTS = tuple(BUSINESS_CENTRAL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: endpoint.incremental_fields for name, endpoint in BUSINESS_CENTRAL_ENDPOINTS.items() if endpoint.cursor_field
}
