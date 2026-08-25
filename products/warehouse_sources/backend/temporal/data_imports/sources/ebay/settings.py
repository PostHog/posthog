from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# eBay serves every marketplace from one host; the marketplace is selected with the
# X-EBAY-C-MARKETPLACE-ID header rather than a regional hostname.
EBAY_API_HOST = "https://api.ebay.com"

# Sell APIs cap a single `filter` date range at 90 days, so historical backfills are
# walked as a series of 90-day windows.
MAX_FILTER_WINDOW_DAYS = 90

# How far back a first sync reaches when there is no stored watermark. eBay's Sell APIs
# only retain roughly two years of seller history, so this covers the readable range.
DEFAULT_BACKFILL_DAYS = 730

# eBay recommends overlapping the cursor by a couple of minutes so orders that were being
# written when the previous run ended aren't skipped.
INCREMENTAL_OVERLAP_SECONDS = 120


@dataclass(frozen=False)  # static endpoint catalog, never mutated after construction
class EbayEndpointConfig:
    name: str
    # Path under the eBay API host, including the Sell API's own version segment.
    path: str
    # Top-level key in the JSON body holding the rows.
    data_key: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField]
    # Declared incremental field name -> the field name used inside eBay's `filter` query
    # param. The Fulfillment API spells its filter fields in lowercase
    # (`lastmodifieddate`), Finances uses camelCase (`transactionDate`).
    filter_fields: dict[str, str] = field(default_factory=dict)
    # Filter field used when the endpoint is synced without an incremental field (or the
    # user's choice isn't filterable). `None` means the endpoint has no date filter at all.
    default_filter_field: Optional[str] = None
    # Page size sent as `limit`. Kept at or under each endpoint's documented maximum.
    page_limit: int = 200
    # Stable datetime column used for partitioning. Must never change for a row.
    partition_key: Optional[str] = None
    # eBay documents no ordering guarantee for these list endpoints, so `desc` is used for
    # every incremental stream: it makes the pipeline finalize the watermark only once the
    # run completes, which is correct no matter what order rows actually arrive in.
    sort_mode: SortMode = "asc"
    # Parent endpoint whose rows supply a required query param (fan-out).
    parent: Optional[str] = None
    # Field read off each parent row, and the query param it is sent as.
    parent_field: Optional[str] = None
    parent_query_param: Optional[str] = None
    extra_params: dict[str, str] = field(default_factory=dict)

    @property
    def supports_time_filter(self) -> bool:
        return self.default_filter_field is not None


def _incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Seller-side streams from eBay's modern Sell REST APIs. The legacy XML Trading API is
# deliberately not used.
EBAY_ENDPOINTS: dict[str, EbayEndpointConfig] = {
    "orders": EbayEndpointConfig(
        name="orders",
        path="/sell/fulfillment/v1/order",
        data_key="orders",
        primary_keys=["orderId"],
        partition_key="creationDate",
        page_limit=200,
        sort_mode="desc",
        incremental_fields=[_incremental_field("lastModifiedDate"), _incremental_field("creationDate")],
        filter_fields={"lastModifiedDate": "lastmodifieddate", "creationDate": "creationdate"},
        default_filter_field="lastmodifieddate",
    ),
    "transactions": EbayEndpointConfig(
        name="transactions",
        path="/sell/finances/v1/transaction",
        data_key="transactions",
        # `transactionId` repeats across transaction types (a SALE carries the order id, a
        # REFUND the refund id), so the type is part of the key.
        primary_keys=["transactionId", "transactionType"],
        partition_key="transactionDate",
        page_limit=200,
        sort_mode="desc",
        incremental_fields=[_incremental_field("transactionDate")],
        filter_fields={"transactionDate": "transactionDate"},
        default_filter_field="transactionDate",
    ),
    "payouts": EbayEndpointConfig(
        name="payouts",
        path="/sell/finances/v1/payout",
        data_key="payouts",
        primary_keys=["payoutId"],
        partition_key="payoutDate",
        page_limit=200,
        sort_mode="desc",
        incremental_fields=[_incremental_field("payoutDate")],
        filter_fields={"payoutDate": "payoutDate"},
        default_filter_field="payoutDate",
    ),
    # The Inventory API has no date filter and no timestamps on its rows, so both of its
    # streams are full refresh with no partition key.
    "inventory_items": EbayEndpointConfig(
        name="inventory_items",
        path="/sell/inventory/v1/inventory_item",
        data_key="inventoryItems",
        primary_keys=["sku"],
        page_limit=100,
        incremental_fields=[],
    ),
    # getOffers requires a SKU, so offers fan out from the inventory item listing. Offer
    # ids are unique across the seller's account, so no parent id is needed in the key.
    "offers": EbayEndpointConfig(
        name="offers",
        path="/sell/inventory/v1/offer",
        data_key="offers",
        primary_keys=["offerId"],
        page_limit=100,
        incremental_fields=[],
        parent="inventory_items",
        parent_field="sku",
        parent_query_param="sku",
    ),
}

ENDPOINTS = tuple(EBAY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in EBAY_ENDPOINTS.items()
}
