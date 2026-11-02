from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Max page size the API allows for classic offset pagination.
PAGE_SIZE = 1000


def _incremental_field(name: str, field_type: IncrementalFieldType) -> IncrementalField:
    return {"label": name, "type": field_type, "field": name, "field_type": field_type}


@dataclass(frozen=True)
class EConomicEndpointConfig:
    name: str
    # Path on https://restapi.e-conomic.com. Uses hyphens (e.g. /customer-groups) while the schema/table
    # name (the dict key) uses underscores.
    path: str
    primary_keys: list[str]
    # Advertised incremental options. Empty => full refresh only. Every advertised field MUST be both
    # server-side filterable (`filter=<field>$gte:<value>`) AND sortable ascending on this endpoint —
    # otherwise the watermark can't checkpoint safely. Verified per-endpoint against the live API.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Field passed as `sort=` on every request. For incremental endpoints it equals the incremental
    # field so rows arrive ascending and the watermark advances correctly. For full-refresh endpoints
    # it's a stable identifier so pagination can't skip/duplicate rows across pages. `None` => no sort
    # (only for tiny single-page endpoints whose number field the API refuses to sort by). Fan-out
    # children sort through `fanout.child_params` instead: rows are only ordered within one parent.
    sort: Optional[str] = None
    # Stable, immutable date field for storage partitioning. Never a field that mutates (e.g.
    # lastUpdated) — partitions would rewrite on every sync.
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    # Set for per-parent sub-collections (e.g. entries per accounting year).
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE
    default_incremental_field: Optional[str] = None


# Endpoint catalog. Incremental support is set ONLY where the live API honors a server-side timestamp /
# monotonic filter AND can sort ascending by that field (both confirmed with curl against the demo
# agreement). Everything else is full refresh — including suppliers (no `lastUpdated`) and draft invoices
# (the API rejects `sort=lastUpdated`, so ascending order can't be guaranteed for a watermark).
E_CONOMIC_ENDPOINTS: dict[str, EConomicEndpointConfig] = {
    "customers": EConomicEndpointConfig(
        name="customers",
        path="/customers",
        primary_keys=["customerNumber"],
        sort="lastUpdated",
        incremental_fields=[_incremental_field("lastUpdated", IncrementalFieldType.DateTime)],
    ),
    "customer_groups": EConomicEndpointConfig(
        name="customer_groups",
        path="/customer-groups",
        primary_keys=["customerGroupNumber"],
        sort="customerGroupNumber",
    ),
    "products": EConomicEndpointConfig(
        name="products",
        path="/products",
        primary_keys=["productNumber"],
        sort="lastUpdated",
        incremental_fields=[_incremental_field("lastUpdated", IncrementalFieldType.DateTime)],
    ),
    "product_groups": EConomicEndpointConfig(
        name="product_groups",
        path="/product-groups",
        primary_keys=["productGroupNumber"],
        sort="productGroupNumber",
    ),
    "suppliers": EConomicEndpointConfig(
        name="suppliers",
        path="/suppliers",
        primary_keys=["supplierNumber"],
        sort="supplierNumber",
    ),
    "supplier_groups": EConomicEndpointConfig(
        name="supplier_groups",
        path="/supplier-groups",
        primary_keys=["supplierGroupNumber"],
        sort="supplierGroupNumber",
    ),
    "accounts": EConomicEndpointConfig(
        name="accounts",
        path="/accounts",
        primary_keys=["accountNumber"],
        sort="accountNumber",
    ),
    "accounting_years": EConomicEndpointConfig(
        name="accounting_years",
        path="/accounting-years",
        primary_keys=["year"],
        sort="year",
    ),
    "journals": EConomicEndpointConfig(
        name="journals",
        path="/journals",
        primary_keys=["journalNumber"],
        sort="journalNumber",
    ),
    "currencies": EConomicEndpointConfig(
        name="currencies",
        path="/currencies",
        primary_keys=["code"],
        sort="code",
    ),
    "payment_terms": EConomicEndpointConfig(
        name="payment_terms",
        path="/payment-terms",
        primary_keys=["paymentTermsNumber"],
        # The API rejects sort=paymentTermsNumber (400); this is a tiny single-page table, so no sort.
        sort=None,
    ),
    "departments": EConomicEndpointConfig(
        name="departments",
        path="/departments",
        primary_keys=["departmentNumber"],
        sort="departmentNumber",
    ),
    "departmental_distributions": EConomicEndpointConfig(
        name="departmental_distributions",
        path="/departmental-distributions",
        primary_keys=["departmentalDistributionNumber"],
        sort="departmentalDistributionNumber",
    ),
    "units": EConomicEndpointConfig(
        name="units",
        path="/units",
        primary_keys=["unitNumber"],
        sort="unitNumber",
    ),
    "vat_zones": EConomicEndpointConfig(
        name="vat_zones",
        path="/vat-zones",
        primary_keys=["vatZoneNumber"],
        sort="vatZoneNumber",
    ),
    # The API accepts `sort` on these three lookups but ignores it, so no sort is sent. Each is a tiny
    # single-page table.
    "vat_types": EConomicEndpointConfig(
        name="vat_types",
        path="/vat-types",
        primary_keys=["vatTypeNumber"],
    ),
    "vat_accounts": EConomicEndpointConfig(
        name="vat_accounts",
        path="/vat-accounts",
        primary_keys=["vatCode"],
    ),
    "payment_types": EConomicEndpointConfig(
        name="payment_types",
        path="/payment-types",
        primary_keys=["paymentTypeNumber"],
    ),
    "employees": EConomicEndpointConfig(
        name="employees",
        path="/employees",
        primary_keys=["employeeNumber"],
        sort="employeeNumber",
    ),
    "invoices_booked": EConomicEndpointConfig(
        name="invoices_booked",
        path="/invoices/booked",
        primary_keys=["bookedInvoiceNumber"],
        # Booked invoices are immutable and numbered monotonically, so the invoice number is a safe,
        # gap-free incremental cursor — unlike `date`, which a user can backdate and would let the
        # watermark skip late entries. `date` is the stable booking date, used only for partitioning.
        sort="bookedInvoiceNumber",
        partition_key="date",
        incremental_fields=[_incremental_field("bookedInvoiceNumber", IncrementalFieldType.Integer)],
    ),
    "invoices_drafts": EConomicEndpointConfig(
        name="invoices_drafts",
        path="/invoices/drafts",
        primary_keys=["draftInvoiceNumber"],
        # Drafts carry `lastUpdated` and the API filters on it, but it refuses sort=lastUpdated, so rows
        # can't be guaranteed ascending for a watermark — full refresh only.
        sort="draftInvoiceNumber",
    ),
    # Orders move draft -> sent -> archived, so a row leaves the drafts and sent tables when its state
    # changes. Full refresh keeps each table an exact snapshot of its state slice.
    "orders_drafts": EConomicEndpointConfig(
        name="orders_drafts",
        path="/orders/drafts",
        primary_keys=["orderNumber"],
        sort="orderNumber",
    ),
    "orders_sent": EConomicEndpointConfig(
        name="orders_sent",
        path="/orders/sent",
        primary_keys=["orderNumber"],
        sort="orderNumber",
    ),
    "orders_archived": EConomicEndpointConfig(
        name="orders_archived",
        path="/orders/archived",
        primary_keys=["orderNumber"],
        sort="orderNumber",
        # Archived orders carry no `lastUpdated` to filter on, so full refresh only.
        partition_key="date",
    ),
    "accounting_year_entries": EConomicEndpointConfig(
        name="accounting_year_entries",
        path="{entries_path}",
        # The entry number restarts with each accounting year, so the year is part of the key.
        primary_keys=["accountingYear", "entryNumber"],
        partition_key="date",
        fanout=DependentEndpointConfig(
            parent_name="accounting_years",
            # Years spanning two calendar years ("2022/2023") use a different form in URLs, so the
            # path comes from the parent's own `entries` link rather than from `year`.
            resolve_param="entries_path",
            resolve_field="entries_path",
            include_from_parent=["year"],
            parent_field_renames={"year": "accountingYear"},
            parent_params={"sort": "year"},
            child_params={"sort": "entryNumber"},
        ),
    ),
    # Entries still in a journal, not yet booked. Booking moves them to accounting_year_entries, so
    # full refresh only.
    "journal_entries": EConomicEndpointConfig(
        name="journal_entries",
        path="/journals/{journalNumber}/entries",
        primary_keys=["journalNumber", "journalEntryNumber"],
        fanout=DependentEndpointConfig(
            parent_name="journals",
            resolve_param="journalNumber",
            resolve_field="journalNumber",
            include_from_parent=["journalNumber"],
            parent_field_renames={"journalNumber": "journalNumber"},
            parent_params={"sort": "journalNumber"},
            child_params={"sort": "journalEntryNumber"},
        ),
    ),
    # Unbooked vouchers, so full refresh like journal_entries. The API rejects every `sort` field here.
    "journal_vouchers": EConomicEndpointConfig(
        name="journal_vouchers",
        path="/journals/{journalNumber}/vouchers",
        # A voucher number is unique per journal and accounting year.
        primary_keys=["journalNumber", "accountingYear", "voucherNumber"],
        fanout=DependentEndpointConfig(
            parent_name="journals",
            resolve_param="journalNumber",
            resolve_field="journalNumber",
            include_from_parent=["journalNumber"],
            parent_field_renames={"journalNumber": "journalNumber"},
            parent_params={"sort": "journalNumber"},
        ),
    ),
    # Balances change while a year is open, so totals are full refresh. The API ignores `sort` here.
    "accounting_year_totals": EConomicEndpointConfig(
        name="accounting_year_totals",
        path="{totals_path}",
        primary_keys=["accountingYear", "accountNumber"],
        fanout=DependentEndpointConfig(
            parent_name="accounting_years",
            resolve_param="totals_path",
            resolve_field="totals_path",
            include_from_parent=["year"],
            parent_field_renames={"year": "accountingYear"},
            parent_params={"sort": "year"},
        ),
    ),
    "accounting_period_totals": EConomicEndpointConfig(
        name="accounting_period_totals",
        path="{totals_path}",
        primary_keys=["accountingYear", "periodNumber", "accountNumber"],
        fanout=DependentEndpointConfig(
            parent_name="accounting_year_periods",
            resolve_param="totals_path",
            resolve_field="totals_path",
            include_from_parent=["periodNumber", "year"],
            parent_field_renames={"periodNumber": "periodNumber", "year": "accountingYear"},
        ),
    ),
}

# Fan-out parents that are not tables themselves. `accounting_period_totals` reaches its totals through
# two hops: accounting_years -> accounting_year_periods -> totals.
E_CONOMIC_FANOUT_PARENTS: dict[str, EConomicEndpointConfig] = {
    "accounting_year_periods": EConomicEndpointConfig(
        name="accounting_year_periods",
        path="{periods_path}",
        primary_keys=["periodNumber"],
        fanout=DependentEndpointConfig(
            parent_name="accounting_years",
            resolve_param="periods_path",
            resolve_field="periods_path",
            include_from_parent=[],
            parent_params={"sort": "year"},
        ),
    ),
}

ENDPOINTS = tuple(E_CONOMIC_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in E_CONOMIC_ENDPOINTS.items()
}
