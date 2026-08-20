from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Display & Video 360 entity API (partners, advertisers, campaigns, line items, ...).
DISPLAY_VIDEO_API_VERSION = "v4"
# Bid Manager reporting API — versioned independently of the entity API and never pinned by the
# user, because a report query built for v2 is not portable to another Bid Manager version.
BID_MANAGER_API_VERSION = "v2"

# "partners"/"advertisers" are single list endpoints; "advertiser_child" fans out per advertiser;
# "report" goes through the async Bid Manager pipeline instead of a list endpoint.
EndpointKind = Literal["partners", "advertisers", "advertiser_child", "report"]


@dataclass(frozen=True)
class DisplayVideo360EndpointConfig:
    name: str
    kind: EndpointKind
    primary_key: list[str]
    # Entity endpoints only. `advertiser_child` paths carry an `{advertiser_id}` placeholder.
    path: str = ""
    # Key in the entity response body holding the list of records.
    data_key: str = ""
    # DV360 caps entity list pages at 200.
    page_size: int = 200
    # Only set when the endpoint can BOTH filter on and order by the field. DV360 lets several
    # endpoints filter on `updateTime` without ordering by it (e.g. creatives), and filtering
    # without a stable order would let the watermark advance past rows we never read.
    incremental_field: Optional[str] = None
    # Report streams: the Bid Manager query this stream generates.
    report_group_bys: tuple[str, ...] = field(default_factory=tuple)
    report_metrics: tuple[str, ...] = field(default_factory=tuple)

    @property
    def supports_incremental(self) -> bool:
        return self.incremental_field is not None


# Metrics requested for every report stream. Kept identical across streams so both report tables
# carry the same measure columns and only differ in grain.
REPORT_METRICS: tuple[str, ...] = (
    "METRIC_IMPRESSIONS",
    "METRIC_BILLABLE_IMPRESSIONS",
    "METRIC_CLICKS",
    "METRIC_CTR",
    "METRIC_TOTAL_CONVERSIONS",
    "METRIC_POST_CLICK_CONVERSIONS",
    "METRIC_POST_VIEW_CONVERSIONS",
    "METRIC_REVENUE_ADVERTISER",
    "METRIC_MEDIA_COST_ADVERTISER",
)

# Report windows are requested a chunk of days at a time so one interrupted sync loses at most a
# chunk, and so a long backfill doesn't ask Bid Manager for a single enormous report.
REPORT_WINDOW_DAYS = 30
# First-sync lookback. DV360 reporting has a bounded retention window, so a longer backfill just
# returns empty rows for the older part.
REPORT_LOOKBACK_DAYS = 90

# Bid Manager renders CSV headers as human labels. Map the ones our queries can emit onto stable
# snake_case column names so the primary keys below don't depend on Google's label wording;
# anything unmapped falls back to a generic slugifier.
REPORT_COLUMN_NAMES: dict[str, str] = {
    "date": "date",
    "advertiser": "advertiser",
    "advertiser id": "advertiser_id",
    "advertiser currency": "advertiser_currency",
    "partner": "partner",
    "partner id": "partner_id",
    "insertion order": "insertion_order",
    "insertion order id": "insertion_order_id",
    "line item": "line_item",
    "line item id": "line_item_id",
    "impressions": "impressions",
    "billable impressions": "billable_impressions",
    "clicks": "clicks",
    "click rate (ctr)": "click_rate",
    "total conversions": "total_conversions",
    "post-click conversions": "post_click_conversions",
    "post-view conversions": "post_view_conversions",
    "revenue (adv currency)": "revenue_advertiser_currency",
    "media cost (advertiser currency)": "media_cost_advertiser_currency",
}


def _update_time_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "updateTime",
            "type": IncrementalFieldType.DateTime,
            "field": "updateTime",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


def _date_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        }
    ]


DISPLAY_VIDEO_360_ENDPOINTS: dict[str, DisplayVideo360EndpointConfig] = {
    "partners": DisplayVideo360EndpointConfig(
        name="partners",
        kind="partners",
        path="/partners",
        data_key="partners",
        primary_key=["partnerId"],
        # Read as `partners/{partnerId}`, not `partners.list`: the list call returns every partner
        # the credential can see, which would reach outside the configured connection scope when one
        # Google account spans several DV360 partners. Full refresh — a single row, and
        # `partners.get` has no updateTime filter or order anyway.
    ),
    "advertisers": DisplayVideo360EndpointConfig(
        name="advertisers",
        kind="advertisers",
        path="/advertisers",
        data_key="advertisers",
        primary_key=["advertiserId"],
        incremental_field="updateTime",
    ),
    "campaigns": DisplayVideo360EndpointConfig(
        name="campaigns",
        kind="advertiser_child",
        path="/advertisers/{advertiser_id}/campaigns",
        data_key="campaigns",
        primary_key=["advertiserId", "campaignId"],
        incremental_field="updateTime",
    ),
    "insertion_orders": DisplayVideo360EndpointConfig(
        name="insertion_orders",
        kind="advertiser_child",
        path="/advertisers/{advertiser_id}/insertionOrders",
        data_key="insertionOrders",
        primary_key=["advertiserId", "insertionOrderId"],
        incremental_field="updateTime",
    ),
    "line_items": DisplayVideo360EndpointConfig(
        name="line_items",
        kind="advertiser_child",
        path="/advertisers/{advertiser_id}/lineItems",
        data_key="lineItems",
        primary_key=["advertiserId", "lineItemId"],
        incremental_field="updateTime",
    ),
    "creatives": DisplayVideo360EndpointConfig(
        name="creatives",
        kind="advertiser_child",
        path="/advertisers/{advertiser_id}/creatives",
        data_key="creatives",
        primary_key=["advertiserId", "creativeId"],
        # `creatives.list` accepts an updateTime filter but cannot order by it, so an incremental
        # run would have no stable order to checkpoint against. Full refresh instead.
    ),
    "advertiser_performance": DisplayVideo360EndpointConfig(
        name="advertiser_performance",
        kind="report",
        primary_key=["date", "advertiser_id"],
        incremental_field="date",
        report_group_bys=("FILTER_DATE", "FILTER_ADVERTISER"),
        report_metrics=REPORT_METRICS,
    ),
    "line_item_performance": DisplayVideo360EndpointConfig(
        name="line_item_performance",
        kind="report",
        primary_key=["date", "advertiser_id", "line_item_id"],
        incremental_field="date",
        report_group_bys=("FILTER_DATE", "FILTER_ADVERTISER", "FILTER_INSERTION_ORDER", "FILTER_LINE_ITEM"),
        report_metrics=REPORT_METRICS,
    ),
}

ENDPOINTS: tuple[str, ...] = tuple(DISPLAY_VIDEO_360_ENDPOINTS)

REPORT_ENDPOINTS: tuple[str, ...] = tuple(
    name for name, config in DISPLAY_VIDEO_360_ENDPOINTS.items() if config.kind == "report"
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: (
        _date_incremental_fields()
        if config.kind == "report"
        else _update_time_incremental_fields()
        if config.supports_incremental
        else []
    )
    for name, config in DISPLAY_VIDEO_360_ENDPOINTS.items()
}
