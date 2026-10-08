from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Three response/pagination shapes Appfigures exposes:
#   - "paged":  /reviews — page/count pagination, flat list under a body key, server-side `start`
#               date filter on the row creation date. Incremental-capable.
#   - "object": /products/mine — a single response that's a JSON object keyed by product id (no
#               pagination, no server-side time filter). Full refresh only.
#   - "report": /reports/* — a single response that's a JSON object keyed by date (group_by=dates),
#               with a `start_date`/`end_date` server-side window and per-granularity range caps, so
#               we walk it in fixed-size date windows. Incremental by date window.
#   - "ranks":  /ranks — a columnar response (a `dates` array plus one series per product/country/
#               category holding position/delta arrays) whose product ids and date range live in the
#               URL path, so we fan out over the account's products in chunks and walk date windows.
#   - "aso":    /aso — a paginated list of the keywords tracked for one product in one country, each
#               carrying its latest position rather than a dated series. One product and one country
#               per request, so we fan out over both and stamp the day the sync ran.
#   - "aso_stats": /aso/stats — the same fan-out, but a single flat object of keyword aggregates per
#               product and country instead of a list.
EndpointKind = Literal["paged", "object", "report", "ranks", "aso", "aso_stats"]


@frozen
class AppfiguresEndpointConfig:
    name: str
    path: str
    kind: EndpointKind
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Stable creation-style field to partition by — never an updated/last-seen field.
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    # Endpoint to probe when validating the token's scope for this schema. Defaults to `path`; set it
    # where `path` carries placeholders and so can't be requested as-is.
    probe_path: Optional[str] = None

    # "paged" endpoints (reviews)
    # Body key the page's rows live under (e.g. {"total":..,"reviews":[...]}).
    data_key: Optional[str] = None
    # Query param name for the server-side creation-date lower bound (yyyy-mm-dd), if any.
    start_param: Optional[str] = None
    # Upper bound param paired with `start_param`. /aso spells the pair start_date/end_date and
    # /aso/stats spells it start/end, so both names come from the config.
    end_param: Optional[str] = None
    # Sort param value to force a stable ascending order so the incremental watermark advances.
    sort: Optional[str] = None
    page_size: int = 500

    # "report" endpoints (reports/*)
    group_by: Optional[str] = None
    granularity: Optional[str] = None
    # Max days fetched per request — daily granularity is capped at 30 days by Appfigures.
    window_days: Optional[int] = None

    # "ranks" endpoints
    # How many product ids to put in one /ranks path. Appfigures caps products x date range per
    # request, so keep chunks well inside it rather than sending the whole catalog.
    products_per_request: int = 20


# `date` on reviews is a full timestamp (e.g. 2017-05-19T17:05:00); on reports it's a day string.
_REVIEW_DATE_FIELD: IncrementalField = {
    "label": "date",
    "type": IncrementalFieldType.DateTime,
    "field": "date",
    "field_type": IncrementalFieldType.DateTime,
}

_REPORT_DATE_FIELD: IncrementalField = {
    "label": "date",
    "type": IncrementalFieldType.Date,
    "field": "date",
    "field_type": IncrementalFieldType.Date,
}


APPFIGURES_ENDPOINTS: dict[str, AppfiguresEndpointConfig] = {
    # The account's product catalog — a small dimension table. Object keyed by product id.
    "products": AppfiguresEndpointConfig(
        name="products",
        path="/products/mine",
        kind="object",
        primary_keys=["id"],
        partition_key="added_date",
    ),
    # App reviews across stores. Paged, with a server-side creation-date filter we drive incrementally.
    "reviews": AppfiguresEndpointConfig(
        name="reviews",
        path="/reviews",
        kind="paged",
        primary_keys=["id"],
        data_key="reviews",
        start_param="start",
        # Appfigures docs: bare `date` sorts ascending (oldest first), `-date` reverses it. Ascending
        # keeps newly-arriving reviews at the tail of the page sequence so earlier pages don't shift
        # mid-backfill (which would otherwise drop the boundary row).
        sort="date",
        partition_key="date",
        default_incremental_field="date",
        incremental_fields=[_REVIEW_DATE_FIELD],
    ),
    # Daily sales (downloads/units) aggregated across the account, one row per day.
    "sales_report": AppfiguresEndpointConfig(
        name="sales_report",
        path="/reports/sales",
        kind="report",
        primary_keys=["date"],
        group_by="dates",
        granularity="daily",
        window_days=30,
        partition_key="date",
        default_incremental_field="date",
        incremental_fields=[_REPORT_DATE_FIELD],
    ),
    # Daily revenue aggregated across the account, one row per day.
    "revenue_report": AppfiguresEndpointConfig(
        name="revenue_report",
        path="/reports/revenue",
        kind="report",
        primary_keys=["date"],
        group_by="dates",
        granularity="daily",
        window_days=30,
        partition_key="date",
        default_incremental_field="date",
        incremental_fields=[_REPORT_DATE_FIELD],
    ),
    # Daily subscription metrics (activations, renewals, churn, MRR) aggregated across the account.
    "subscriptions_report": AppfiguresEndpointConfig(
        name="subscriptions_report",
        path="/reports/subscriptions",
        kind="report",
        primary_keys=["date"],
        group_by="dates",
        granularity="daily",
        window_days=30,
        partition_key="date",
        default_incremental_field="date",
        incremental_fields=[_REPORT_DATE_FIELD],
    ),
    # Daily rating counts and averages across the account. The supported replacement for /ratings.
    "ratings_report": AppfiguresEndpointConfig(
        name="ratings_report",
        path="/reports/ratings",
        kind="report",
        primary_keys=["date"],
        group_by="dates",
        granularity="daily",
        window_days=30,
        partition_key="date",
        default_incremental_field="date",
        incremental_fields=[_REPORT_DATE_FIELD],
    ),
    # Daily ad-publishing revenue by network: requests, fill rate, impressions, eCPM, and the
    # revenue those ads earned, which the sales and revenue reports do not cover.
    "ads_report": AppfiguresEndpointConfig(
        name="ads_report",
        path="/reports/ads",
        kind="report",
        primary_keys=["date"],
        group_by="dates",
        granularity="daily",
        window_days=30,
        partition_key="date",
        default_incremental_field="date",
        incremental_fields=[_REPORT_DATE_FIELD],
    ),
    # Daily user-acquisition campaign spend: installs, clicks, impressions, cost, CPC, and CPA, so
    # spend can be set against the revenue report.
    "adspend_report": AppfiguresEndpointConfig(
        name="adspend_report",
        path="/reports/adspend",
        kind="report",
        primary_keys=["date"],
        group_by="dates",
        granularity="daily",
        window_days=30,
        partition_key="date",
        default_incremental_field="date",
        incremental_fields=[_REPORT_DATE_FIELD],
    ),
    # Daily expected payouts, which reconcile recognized revenue to the cash the stores pay out.
    "payments_report": AppfiguresEndpointConfig(
        name="payments_report",
        path="/reports/payments",
        kind="report",
        primary_keys=["date"],
        group_by="dates",
        granularity="daily",
        window_days=30,
        partition_key="date",
        default_incremental_field="date",
        incremental_fields=[_REPORT_DATE_FIELD],
    ),
    # Store category rank history per product, country, and category.
    "ranks": AppfiguresEndpointConfig(
        name="ranks",
        path="/ranks",
        kind="ranks",
        # A category id repeats across its free/paid/topgrossing charts, so the subtype is part of
        # what makes a rank observation unique.
        primary_keys=["date", "product_id", "country", "category_id", "category_subtype"],
        granularity="daily",
        window_days=30,
        partition_key="date",
        default_incremental_field="date",
        incremental_fields=[_REPORT_DATE_FIELD],
        # /ranks takes its product ids in the path, so there is no cheap request to probe. Ranks and
        # reviews both need `public:read`, so probing reviews checks the same grant.
        probe_path="/reviews",
    ),
    # Search position of every keyword tracked in Appfigures, per product and country. Appfigures
    # returns the latest position rather than a dated series, so each sync stamps the day it ran and
    # the table builds up a daily snapshot per keyword.
    "aso_keywords": AppfiguresEndpointConfig(
        name="aso_keywords",
        path="/aso",
        kind="aso",
        primary_keys=["date", "product_id", "country", "keyword_id"],
        data_key="results",
        start_param="start_date",
        end_param="end_date",
        granularity="daily",
        window_days=30,
        partition_key="date",
        # One request per product per country, paginated. Requests cost account credits, so leave it
        # to the user to turn on once they have picked the countries they track keywords in.
        should_sync_default=False,
        # /aso needs a product and a country, so there is no cheap request to probe. The fan-out
        # reads the product catalog before anything else, so probe that instead.
        probe_path="/products/mine",
    ),
    # Per-product, per-country summary of the tracked keyword set: average position, how many
    # keywords sit in the top 5/25/100, and how many moved up or down.
    "aso_stats": AppfiguresEndpointConfig(
        name="aso_stats",
        path="/aso/stats",
        kind="aso_stats",
        primary_keys=["date", "product_id", "country"],
        start_param="start",
        end_param="end",
        granularity="daily",
        window_days=30,
        partition_key="date",
        should_sync_default=False,
        probe_path="/products/mine",
    ),
    # Store metadata resolving the `store` / `store_id` codes on products and rank rows.
    "stores": AppfiguresEndpointConfig(
        name="stores",
        path="/data/stores",
        kind="object",
        primary_keys=["id"],
    ),
    # Category metadata resolving the `category_id` on rank rows.
    "categories": AppfiguresEndpointConfig(
        name="categories",
        path="/data/categories",
        kind="object",
        primary_keys=["id"],
    ),
    # Country metadata resolving the ISO codes on reviews, reports, and rank rows.
    "countries": AppfiguresEndpointConfig(
        name="countries",
        path="/data/countries",
        kind="object",
        primary_keys=["iso"],
    ),
}

ENDPOINTS = tuple(APPFIGURES_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APPFIGURES_ENDPOINTS.items()
}
