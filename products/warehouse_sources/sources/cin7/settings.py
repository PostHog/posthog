from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

CIN7_BASE_URL = "https://inventory.dearsystems.com/ExternalApi/v2"

# Cin7 Core caps `Limit` at 1000 rows per page.
PAGE_LIMIT = 1000


def _datetime_field(name: str) -> list[IncrementalField]:
    return [
        {
            "label": name,
            "type": IncrementalFieldType.DateTime,
            "field": name,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


@dataclass(frozen=True)
class Cin7Endpoint:
    name: str
    path: str
    data_selector: str
    # None for endpoints whose rows have no unique identifier. These stay on full refresh.
    primary_keys: Optional[list[str]] = field(default_factory=lambda: ["ID"])
    # The query parameter that filters rows changed after a date. None means full refresh only.
    incremental_filter_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    paginated: bool = True


_ENDPOINT_LIST: list[Cin7Endpoint] = [
    # Without IncludeDeprecated the API leaves deprecated records out, so a deprecation would never sync.
    Cin7Endpoint(
        name="products",
        path="/product",
        data_selector="Products",
        incremental_filter_param="ModifiedSince",
        incremental_fields=_datetime_field("LastModifiedOn"),
        params={"IncludeDeprecated": "true"},
    ),
    # LastModifiedOn is nullable on product families, so they stay on full refresh.
    Cin7Endpoint(name="product_families", path="/productFamily", data_selector="ProductFamilies"),
    # One row per product, location, bin and batch.
    Cin7Endpoint(
        name="product_availability",
        path="/ref/productavailability",
        data_selector="ProductAvailabilityList",
        primary_keys=["ID", "Location", "Bin", "Batch"],
    ),
    Cin7Endpoint(name="product_categories", path="/ref/category", data_selector="CategoryList"),
    Cin7Endpoint(name="brands", path="/ref/brand", data_selector="BrandList"),
    Cin7Endpoint(
        name="customers",
        path="/customer",
        data_selector="CustomerList",
        incremental_filter_param="ModifiedSince",
        incremental_fields=_datetime_field("LastModifiedOn"),
        params={"IncludeDeprecated": "true"},
    ),
    Cin7Endpoint(
        name="suppliers",
        path="/supplier",
        data_selector="SupplierList",
        incremental_filter_param="ModifiedSince",
        incremental_fields=_datetime_field("LastModifiedOn"),
        params={"IncludeDeprecated": "true"},
    ),
    Cin7Endpoint(
        name="sales",
        path="/saleList",
        data_selector="SaleList",
        primary_keys=["SaleID"],
        incremental_filter_param="UpdatedSince",
        incremental_fields=_datetime_field("Updated"),
    ),
    # The credit note list returns one row per sale, under the same `SaleList` key as the sale list.
    Cin7Endpoint(
        name="sale_credit_notes",
        path="/saleCreditNoteList",
        data_selector="SaleList",
        primary_keys=["SaleID"],
        incremental_filter_param="UpdatedSince",
        incremental_fields=_datetime_field("Updated"),
    ),
    Cin7Endpoint(
        name="purchases",
        path="/purchaseList",
        data_selector="PurchaseList",
        incremental_filter_param="UpdatedSince",
        incremental_fields=_datetime_field("LastUpdatedDate"),
    ),
    Cin7Endpoint(
        name="purchase_credit_notes",
        path="/purchaseCreditNoteList",
        data_selector="PurchaseList",
        incremental_filter_param="UpdatedSince",
        incremental_fields=_datetime_field("LastUpdatedDate"),
    ),
    Cin7Endpoint(
        name="stock_adjustments",
        path="/stockadjustmentList",
        data_selector="StockAdjustmentList",
        primary_keys=["TaskID"],
    ),
    # The stock take list also answers under the `StockAdjustmentList` key.
    Cin7Endpoint(
        name="stock_takes",
        path="/stockTakeList",
        data_selector="StockAdjustmentList",
        primary_keys=["TaskID"],
    ),
    Cin7Endpoint(
        name="stock_transfers",
        path="/stockTransferList",
        data_selector="StockTransferList",
        primary_keys=["TaskID"],
    ),
    Cin7Endpoint(name="locations", path="/ref/location", data_selector="LocationList"),
    Cin7Endpoint(name="payment_terms", path="/ref/paymentterm", data_selector="PaymentTermList"),
    Cin7Endpoint(
        name="chart_of_accounts",
        path="/ref/account",
        data_selector="AccountsList",
        primary_keys=["Code"],
    ),
    Cin7Endpoint(name="tax_rules", path="/ref/tax", data_selector="TaxRuleList"),
    Cin7Endpoint(name="units_of_measure", path="/ref/unit", data_selector="UnitList"),
    Cin7Endpoint(name="carriers", path="/ref/carrier", data_selector="CarrierList", primary_keys=["CarrierID"]),
    Cin7Endpoint(
        name="price_tiers",
        path="/ref/priceTier",
        data_selector="PriceTiers",
        primary_keys=["Code"],
        paginated=False,
    ),
    Cin7Endpoint(
        name="production_orders",
        path="/production/orderList",
        data_selector="ProductionOrderListItems",
        primary_keys=["TaskID"],
    ),
    # Without ShowUsedCredits the API leaves fully used credits out, so they would drop from the table.
    Cin7Endpoint(
        name="customer_credits",
        path="/ref/customer/credits",
        data_selector="CustomerCredits",
        primary_keys=["CreditID"],
        params={"ShowUsedCredits": "true"},
    ),
    Cin7Endpoint(name="journals", path="/journal", data_selector="Journals", primary_keys=["TaskID"]),
    # One task posts many ledger lines and the rows carry no line ID. FromDate filters on
    # EffectiveDate, not on a change time, so back-dated postings would be missed incrementally.
    Cin7Endpoint(name="transactions", path="/transactions", data_selector="Transactions", primary_keys=None),
]

CIN7_ENDPOINTS: dict[str, Cin7Endpoint] = {endpoint.name: endpoint for endpoint in _ENDPOINT_LIST}

ENDPOINTS = tuple(CIN7_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint.name: endpoint.incremental_fields for endpoint in _ENDPOINT_LIST if endpoint.incremental_fields
}
