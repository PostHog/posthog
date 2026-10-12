from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _incremental_field(name: str, field_type: IncrementalFieldType) -> IncrementalField:
    return {"label": name, "type": field_type, "field": name, "field_type": field_type}


@dataclass
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
    # (only for tiny single-page endpoints whose number field the API refuses to sort by).
    sort: Optional[str] = None
    # Stable, immutable date field for storage partitioning. Never a field that mutates (e.g.
    # lastUpdated) — partitions would rewrite on every sync.
    partition_key: Optional[str] = None
    should_sync_default: bool = True


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
}

ENDPOINTS = tuple(E_CONOMIC_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in E_CONOMIC_ENDPOINTS.items()
}
