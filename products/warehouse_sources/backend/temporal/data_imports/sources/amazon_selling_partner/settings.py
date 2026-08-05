from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

EndpointKind = Literal["list", "fanout", "report"]


@dataclass(frozen=True)
class SpApiEndpointConfig:
    name: str
    kind: EndpointKind
    primary_key: list[str]
    # Path under the regional Selling Partner API host. `fanout` paths carry an
    # `{order_id}` placeholder filled per parent row.
    path: str = ""
    # Key holding the row list, looked up inside the `payload` envelope when there is one.
    data_key: str = ""
    # SP-API is inconsistent: v0 operations use `NextToken`, the newer ones `nextToken`.
    token_param: str = "NextToken"
    page_size_param: str | None = None
    page_size: int | None = None
    # Server-side timestamp filter. Absent means the endpoint can only full refresh.
    since_param: str | None = None
    # Query param carrying the marketplace ids, comma-joined. None = not accepted.
    marketplace_param: str | None = None
    # Extra static query params sent on every request.
    extra_params: dict[str, str] = field(default_factory=dict)
    # True when the endpoint is scoped to one marketplace at a time and has to be
    # walked once per configured marketplace.
    per_marketplace: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: str | None = None
    # SP-API documents no ordering guarantee for its list operations, so rows are
    # declared `desc` — that defers the incremental watermark commit to the end of a
    # run instead of trusting per-batch ordering that Amazon never promised.
    sort_mode: SortMode = "desc"
    report_type: str | None = None
    report_options: dict[str, str] = field(default_factory=dict)
    # Key holding the row list inside a downloaded JSON report document.
    report_rows_key: str | None = None


AMAZON_SELLING_PARTNER_ENDPOINTS: dict[str, SpApiEndpointConfig] = {
    "orders": SpApiEndpointConfig(
        name="orders",
        kind="list",
        path="/orders/v0/orders",
        data_key="Orders",
        token_param="NextToken",
        page_size_param="MaxResultsPerPage",
        page_size=100,
        since_param="LastUpdatedAfter",
        marketplace_param="MarketplaceIds",
        primary_key=["AmazonOrderId"],
        incremental_fields=[incremental_field("LastUpdateDate")],
        partition_key="PurchaseDate",
    ),
    "order_items": SpApiEndpointConfig(
        name="order_items",
        kind="fanout",
        path="/orders/v0/orders/{order_id}/orderItems",
        data_key="OrderItems",
        token_param="NextToken",
        primary_key=["AmazonOrderId", "OrderItemId"],
        # Order items carry no timestamp of their own — the parent order's last-update
        # timestamp is injected onto each row and drives the watermark.
        incremental_fields=[incremental_field("_order_last_update_date")],
        partition_key="_order_purchase_date",
    ),
    "financial_transactions": SpApiEndpointConfig(
        name="financial_transactions",
        kind="list",
        # Finances v0 is being removed; 2024-06-19 is the current surface.
        path="/finances/2024-06-19/transactions",
        data_key="transactions",
        token_param="nextToken",
        since_param="postedAfter",
        primary_key=["transactionId"],
        incremental_fields=[incremental_field("postedDate")],
        partition_key="postedDate",
    ),
    "fba_inventory": SpApiEndpointConfig(
        name="fba_inventory",
        kind="list",
        path="/fba/inventory/v1/summaries",
        data_key="inventorySummaries",
        token_param="nextToken",
        since_param="startDateTime",
        marketplace_param="marketplaceIds",
        extra_params={"granularityType": "Marketplace", "details": "true"},
        per_marketplace=True,
        primary_key=["sellerSku", "_marketplace_id"],
        incremental_fields=[incremental_field("lastUpdatedTime")],
        # Every candidate timestamp on an inventory summary is restated, so there is no
        # stable datetime to partition on.
        partition_key=None,
    ),
    "sales_and_traffic": SpApiEndpointConfig(
        name="sales_and_traffic",
        kind="report",
        primary_key=["date"],
        report_type="GET_SALES_AND_TRAFFIC_REPORT",
        report_options={"dateGranularity": "DAY", "asinGranularity": "PARENT"},
        report_rows_key="salesAndTrafficByDate",
        incremental_fields=[incremental_field("date", IncrementalFieldType.Date)],
        partition_key="date",
        # Report windows are requested oldest-first and each document is ordered by date.
        sort_mode="asc",
    ),
}

ENDPOINTS = tuple(AMAZON_SELLING_PARTNER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AMAZON_SELLING_PARTNER_ENDPOINTS.items()
}
