from typing import NotRequired, TypedDict

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class SearchAnalyticsSchema(TypedDict):
    dimensions: list[str]
    primary_key: list[str]
    should_sync_default: bool
    description: str | None
    # `dataState` sent with the query. Defaults to final (complete) data.
    data_state: NotRequired[str]
    # How far back the first sync reaches, when the endpoint retains less than the
    # 16 months Search Analytics keeps for daily data.
    history_days: NotRequired[int]
    # How many days behind today the window ends, covering Google's publishing lag.
    end_lag_days: NotRequired[int]
    # Refetch the whole retention window every sync instead of resuming at the
    # watermark. Only sane for tables whose window is a handful of days and whose
    # rows Google keeps restating.
    ignore_incremental_watermark: NotRequired[bool]
    # Offer this table for web search only. Google documents neither support nor a
    # restriction for pairing `hour`/`searchAppearance` with a non-web `type`, so these
    # stay web-only rather than shipping tables that may silently sync nothing.
    web_only: NotRequired[bool]


DEFAULT_SEARCH_TYPE = "web"
# Google's `type` parameter. `discover` and `googleNews` are deliberately left out: both
# reject `aggregationType=byProperty` and behave differently enough to need their own
# dimension catalog rather than a cross product with the schemas below.
SEARCH_TYPES = ("web", "image", "video", "news")
NON_WEB_SEARCH_TYPES = tuple(t for t in SEARCH_TYPES if t != DEFAULT_SEARCH_TYPE)


# Each schema maps to a single Search Analytics query with a fixed dimension set.
# Primary key is always (date + dimensions) to allow merge-mode dedupe across re-syncs.
#
# Sampling note: Google's Search Analytics API caps results at ~50,000 rows per
# (property, date, dimension-set). When the cap is hit, rows are sorted by clicks
# descending and the tail is silently dropped. Schemas with more dimensions hit
# the cap faster (see `search_analytics_by_query_page` below). For full-fidelity
# data on high-traffic properties, the official BigQuery bulk export is the only
# escape hatch; see `google_search_console.py` for the full breakdown.
SEARCH_ANALYTICS_SCHEMAS: dict[str, SearchAnalyticsSchema] = {
    "search_analytics_by_date": {
        "dimensions": ["date"],
        "primary_key": ["date"],
        "should_sync_default": False,
        "description": "Daily totals for clicks, impressions, CTR, and average position.",
    },
    "search_analytics_by_query": {
        "dimensions": ["date", "query"],
        "primary_key": ["date", "query"],
        "should_sync_default": False,
        "description": (
            "Daily performance broken out by search query (keyword). "
            "Sites with >50K distinct queries/day will lose long-tail keywords to API sampling."
        ),
    },
    "search_analytics_by_page": {
        "dimensions": ["date", "page"],
        "primary_key": ["date", "page"],
        "should_sync_default": False,
        "description": (
            "Daily performance broken out by landing page URL. "
            "Sites with >50K distinct landing pages/day will lose long-tail URLs to API sampling."
        ),
    },
    "search_analytics_by_country": {
        "dimensions": ["date", "country"],
        "primary_key": ["date", "country"],
        "should_sync_default": False,
        "description": "Daily performance broken out by country (ISO 3166-1 alpha-3).",
    },
    "search_analytics_by_device": {
        "dimensions": ["date", "device"],
        "primary_key": ["date", "device"],
        "should_sync_default": False,
        "description": "Daily performance broken out by device (DESKTOP, MOBILE, TABLET).",
    },
    "search_analytics_by_country_device": {
        "dimensions": ["date", "country", "device"],
        "primary_key": ["date", "country", "device"],
        "should_sync_default": False,
        "description": (
            "Daily performance broken out by country and device together. Low cardinality "
            "(countries x three device types), so it stays well under the row sampling cap."
        ),
    },
    "search_analytics_by_page_device": {
        "dimensions": ["date", "page", "device"],
        "primary_key": ["date", "page", "device"],
        "should_sync_default": False,
        "description": (
            "Daily performance broken out by landing page and device together. Answers questions "
            "like mobile CTR per landing page. Roughly three rows per page per day, so it hits "
            "Google's ~50K row/day API sampling cap about three times sooner than the per-page table."
        ),
    },
    "search_analytics_by_page_country": {
        "dimensions": ["date", "page", "country"],
        "primary_key": ["date", "page", "country"],
        "should_sync_default": False,
        "description": (
            "Daily performance broken out by landing page and country together. One row per page "
            "per country per day, so it reaches Google's ~50K row/day API sampling cap much sooner "
            "than the per-page table and long-tail pages drop out first."
        ),
    },
    "search_analytics_by_query_device": {
        "dimensions": ["date", "query", "device"],
        "primary_key": ["date", "query", "device"],
        "should_sync_default": False,
        "description": (
            "Daily performance broken out by search query and device together. Roughly three rows "
            "per query per day, so it hits Google's ~50K row/day API sampling cap about three times "
            "sooner than the per-query table."
        ),
    },
    "search_analytics_by_query_country": {
        "dimensions": ["date", "query", "country"],
        "primary_key": ["date", "query", "country"],
        "should_sync_default": False,
        "description": (
            "Daily performance broken out by search query and country together. The highest "
            "cardinality table here after query x page: on multi-country sites it can hit Google's "
            "~50K row/day API sampling cap sooner than query x page does. Above the cap only the "
            "top rows by clicks are returned and the tail is silently dropped."
        ),
    },
    # `hour` is the only dimension Google serves outside the 16-month daily window: it
    # retains 10 days and requires `dataState: hourly_all`, which mixes complete and
    # partial rows. Because Google keeps restating those rows for a few days, every sync
    # refetches the whole 10-day window rather than resuming at the watermark.
    "search_analytics_by_hour": {
        "dimensions": ["hour"],
        "primary_key": ["date", "hour"],
        "should_sync_default": False,
        "description": (
            "Hourly totals for clicks, impressions, CTR, and average position. Google only "
            "keeps 10 days of hourly data, and the most recent hours are partial until they "
            "settle, so recent rows can change between syncs."
        ),
        "data_state": "hourly_all",
        "history_days": 10,
        "end_lag_days": 0,
        "ignore_incremental_watermark": True,
        "web_only": True,
    },
    "search_analytics_by_query_page": {
        "dimensions": ["date", "query", "page"],
        "primary_key": ["date", "query", "page"],
        "should_sync_default": True,
        "description": (
            "Daily performance broken out by both query and landing page. Most detailed table, "
            "but the cartesian over (query x page) hits Google's ~50K row/day API sampling cap "
            "fastest. Above the cap, only the top rows by clicks are returned and the tail is "
            "silently dropped. For full fidelity on high-traffic properties, use the per-query "
            "and per-page tables together, or rely on Google's BigQuery bulk export."
        ),
    },
    # Google's Search Analytics API does NOT allow `searchAppearance` to be grouped
    # with any other dimension — including `date`. The per-day partitioning comes
    # from the iterator querying one day at a time and injecting the iteration date
    # into each row (see `_row_to_dict`).
    "search_analytics_by_search_appearance": {
        "dimensions": ["searchAppearance"],
        "primary_key": ["date", "searchAppearance"],
        "should_sync_default": False,
        "description": (
            "Daily performance broken out by Google search result presentation type "
            "(e.g. RICH_RESULT, REVIEW_SNIPPET, FAQ_RICH_RESULT, VIDEO, AMP_BLUE_LINK). "
            "Useful for measuring the impact of structured data and rich result eligibility."
        ),
        "web_only": True,
    },
}


def qualified_schema_name(base_name: str, search_type: str) -> str:
    """Table name for a schema restricted to `search_type`.

    Web keeps the bare name so sources created before search types existed keep their
    tables. A single underscore is required: `NamingConvention` collapses runs of
    underscores, so a `__` separator would make the schema name and the warehouse table
    name diverge.
    """
    return base_name if search_type == DEFAULT_SEARCH_TYPE else f"{base_name}_{search_type}"


def split_schema_name(schema_name: str) -> tuple[str, str]:
    """Inverse of `qualified_schema_name`, as (base name, search type).

    Only splits when the remainder is a known base, so an unrecognized name comes back
    untouched and the caller's unknown-schema guard still fires.
    """
    for search_type in NON_WEB_SEARCH_TYPES:
        base_name = schema_name.removesuffix(f"_{search_type}")
        if base_name != schema_name and base_name in SEARCH_ANALYTICS_SCHEMAS:
            return base_name, search_type
    return schema_name, DEFAULT_SEARCH_TYPE


class PropertySchema(TypedDict):
    primary_key: list[str]
    should_sync_default: bool
    description: str | None


# Property-level metadata, sourced from `sites.list` and `sitemaps.list`. Both are single
# unpaginated GETs returning tens of rows, with no timestamp filter to sync incrementally
# on, so they are full-refresh snapshots of the current state.
PROPERTY_SCHEMAS: dict[str, PropertySchema] = {
    "sites": {
        "primary_key": ["siteUrl"],
        "should_sync_default": True,
        "description": (
            "Every Search Console property the connected Google account can see, with the "
            "account's permission level on each one."
        ),
    },
    "sitemaps": {
        "primary_key": ["path"],
        "should_sync_default": True,
        "description": (
            "Sitemaps submitted for this property, with when Google last downloaded each one "
            "and how many errors and warnings it found."
        ),
    },
    "sitemap_contents": {
        "primary_key": ["path", "type"],
        "should_sync_default": True,
        "description": (
            "URL counts per content type (web, image, video, news) for each submitted sitemap. "
            "One row per sitemap and content type."
        ),
    },
}


SEARCH_ANALYTICS_INCREMENTAL_FIELD: IncrementalField = {
    "label": "date",
    "field": "date",
    "type": IncrementalFieldType.Date,
    "field_type": IncrementalFieldType.Date,
}
