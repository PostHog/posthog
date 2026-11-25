from typing import Literal

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    frozen,
)

BASE_URLS = {
    "us": "https://api.eflow.team/v1",
    "eu": "https://api-eu.eflow.team/v1",
}

# The documented maximum page size on the entity tables.
TABLE_PAGE_SIZE = 2000
# Everflow does not state a maximum for the conversions report, the invoices table or the adjustments
# table, so these stay well under the table limit.
CONVERSIONS_PAGE_SIZE = 500
INVOICES_PAGE_SIZE = 500
ADJUSTMENTS_PAGE_SIZE = 500

# Everflow's timezone id for UTC. Response timestamps are always UTC; this pins how `from`/`to` dates read.
UTC_TIMEZONE_ID = 67

# The conversions report only reaches the prior 365 days.
HISTORY_DAYS = 365

# Conversion statuses and payouts change after the conversion, and daily totals follow them, so each
# incremental run re-reads the last month. The conversions cursor is an epoch integer, which the
# pipeline's lookback skips, so the source applies that table's re-read itself.
REREAD_DAYS = 30
LOOKBACK_SECONDS = REREAD_DAYS * 24 * 60 * 60
# An adjustment can be entered for any earlier day, so each run re-reads the full year and merges. Rows
# older than the window stay in the table.
ADJUSTMENTS_LOOKBACK_SECONDS = HISTORY_DAYS * 24 * 60 * 60


@frozen
class EverflowEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_keys: tuple[str, ...]
    method: Literal["GET", "POST"] = "POST"
    # None means the endpoint returns everything in one response, with no `paging` object.
    page_size: int | None = TABLE_PAGE_SIZE
    incremental_fields: tuple[IncrementalField, ...] = ()
    partition_key: str | None = None
    default_incremental_lookback_seconds: int | None = None
    # Columns that carry credentials and must never reach the warehouse.
    drop_columns: tuple[str, ...] = ()
    # Fields Everflow documents as numbers but sends as a JSON integer when whole. Without the cast, a
    # first batch of whole values creates the column as int64 and a later fractional value fails the load.
    float_columns: tuple[str, ...] = ()
    fanout: DependentEndpointConfig | None = None


EVERFLOW_ENDPOINTS: dict[str, EverflowEndpointConfig] = {
    "offers": EverflowEndpointConfig(
        name="offers",
        path="/networks/offerstable",
        data_selector="offers",
        primary_keys=("network_offer_id",),
        # `payout` and `revenue` hold formatted text, so only the `*_amount` fields are numbers.
        float_columns=("payout_amount", "revenue_amount", "today_payout_amount", "today_revenue_amount"),
    ),
    "affiliates": EverflowEndpointConfig(
        name="affiliates",
        path="/networks/affiliatestable",
        data_selector="affiliates",
        primary_keys=("network_affiliate_id",),
    ),
    "advertisers": EverflowEndpointConfig(
        name="advertisers",
        path="/networks/advertiserstable",
        data_selector="advertisers",
        primary_keys=("network_advertiser_id",),
        # The token that authenticates the advertiser's conversion postbacks.
        drop_columns=("verification_token",),
    ),
    "conversions": EverflowEndpointConfig(
        name="conversions",
        path="/networks/reporting/conversions",
        data_selector="conversions",
        primary_keys=("conversion_id",),
        page_size=CONVERSIONS_PAGE_SIZE,
        partition_key="conversion_unix_timestamp",
        float_columns=("payout", "revenue", "sale_amount"),
        incremental_fields=(
            {
                "label": "conversion_unix_timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "conversion_unix_timestamp",
                "field_type": IncrementalFieldType.Integer,
            },
        ),
    ),
    "daily_performance": EverflowEndpointConfig(
        name="daily_performance",
        path="/networks/reporting/entity/table",
        data_selector="table",
        primary_keys=("date", "network_offer_id", "network_affiliate_id"),
        page_size=None,
        # Every amount and rate in the report's `reporting` object. Its counts (clicks, conversions, events)
        # are documented as integers and stay int64.
        float_columns=(
            "avg_sale_value",
            "cpa",
            "cpc",
            "cpm",
            "ctr",
            "cvr",
            "epc",
            "event_revenue",
            "evr",
            "gross_sales",
            "margin",
            "media_buying_cost",
            "on_hold_potential_payout",
            "on_hold_potential_revenue",
            "payout",
            "profit",
            "revenue",
            "roas",
            "rpa",
            "rpc",
            "rpm",
        ),
        incremental_fields=(
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            },
        ),
        partition_key="date",
        default_incremental_lookback_seconds=LOOKBACK_SECONDS,
    ),
    "categories": EverflowEndpointConfig(
        name="categories",
        path="/networks/categories",
        method="GET",
        data_selector="categories",
        primary_keys=("network_category_id",),
        page_size=None,
    ),
    "affiliate_tiers": EverflowEndpointConfig(
        name="affiliate_tiers",
        path="/networks/affiliatetiers",
        method="GET",
        data_selector="tiers",
        primary_keys=("network_affiliate_tier_id",),
        page_size=None,
        float_columns=("payout_margin",),
    ),
    "partner_invoices": EverflowEndpointConfig(
        name="partner_invoices",
        path="/networks/billings/affiliates/invoicestable",
        data_selector="invoices",
        primary_keys=("network_affiliate_invoice_id",),
        page_size=INVOICES_PAGE_SIZE,
        float_columns=("balance", "billed", "paid"),
    ),
    "affiliate_users": EverflowEndpointConfig(
        name="affiliate_users",
        path="/networks/affiliates/{network_affiliate_id}/users",
        method="GET",
        data_selector="users",
        primary_keys=("network_affiliate_id", "network_affiliate_user_id"),
        page_size=None,
        fanout=DependentEndpointConfig(
            parent_name="affiliates",
            resolve_param="network_affiliate_id",
            resolve_field="network_affiliate_id",
            include_from_parent=["network_affiliate_id"],
            parent_field_renames={"network_affiliate_id": "network_affiliate_id"},
            parent_params={"page_size": TABLE_PAGE_SIZE},
            # A partner deleted between the partner listing and its users request returns 404.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "labels": EverflowEndpointConfig(
        name="labels",
        path="/networks/labels",
        method="GET",
        data_selector="labels",
        primary_keys=("label",),
        page_size=None,
    ),
    "traffic_sources": EverflowEndpointConfig(
        name="traffic_sources",
        path="/networks/trafficsource",
        method="GET",
        data_selector="traffic_sources",
        primary_keys=("network_traffic_source_id",),
        page_size=None,
    ),
    "creatives": EverflowEndpointConfig(
        name="creatives",
        path="/networks/creativestable",
        data_selector="creatives",
        primary_keys=("network_offer_creative_id",),
    ),
    "reporting_adjustments": EverflowEndpointConfig(
        name="reporting_adjustments",
        path="/networks/reportingadjustments/table",
        data_selector="adjustments",
        primary_keys=("network_reporting_adjustment_id",),
        page_size=ADJUSTMENTS_PAGE_SIZE,
        float_columns=("gross_sales", "media_buying_cost", "payout", "revenue"),
        incremental_fields=(
            {
                "label": "date_adjustment",
                "type": IncrementalFieldType.Date,
                "field": "date_adjustment",
                "field_type": IncrementalFieldType.Date,
            },
        ),
        default_incremental_lookback_seconds=ADJUSTMENTS_LOOKBACK_SECONDS,
    ),
}

ENDPOINTS = tuple(EVERFLOW_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(config.incremental_fields) for name, config in EVERFLOW_ENDPOINTS.items()
}

LOOKBACK: dict[str, int] = {
    name: config.default_incremental_lookback_seconds
    for name, config in EVERFLOW_ENDPOINTS.items()
    if config.default_incremental_lookback_seconds is not None
}

# These tables re-read a trailing window each run. Appending would write those rows again.
MERGE_ONLY = ("conversions", "daily_performance", "reporting_adjustments")

# Report tables that require a `from`/`to` date window in the request body.
WINDOWED_ENDPOINTS = ("conversions", "reporting_adjustments")
