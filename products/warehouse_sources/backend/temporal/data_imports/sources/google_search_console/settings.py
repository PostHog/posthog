from typing import NotRequired, TypedDict

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class SearchAnalyticsSchema(TypedDict):
    dimensions: list[str]
    primary_key: list[str]
    should_sync_default: bool
    description: str | None
    # `dataState` sent with the query. Defaults to final (complete) data.
    data_state: NotRequired[str]
    # `type` values the table fans out over, one request per type per day. Search Analytics
    # defaults to `web`, so a table that omits this covers web search only. A table listing
    # more than one carries the type as a `search_type` column in its primary key.
    search_types: NotRequired[list[str]]
    # How far back the first sync reaches, when the endpoint retains less than the
    # 16 months Search Analytics keeps for daily data.
    history_days: NotRequired[int]
    # How many days behind today the window ends, covering Google's publishing lag.
    end_lag_days: NotRequired[int]
    # Refetch the whole retention window every sync instead of resuming at the
    # watermark. Only sane for tables whose window is a handful of days and whose
    # rows Google keeps restating.
    ignore_incremental_watermark: NotRequired[bool]


# The tabs Search Analytics reports on via `type`. Discover and Google News are separate
# surfaces Google serves under the same field, but they don't answer the same dimensions
# (no query, for one), so they aren't part of the fan-out.
SEARCH_TYPE_TABS: list[str] = ["web", "image", "video", "news"]


def _web_only(description: str) -> str:
    """Note the web-only scope Search Analytics applies when a query omits `type`.

    Google's default is invisible in the response, so a table that doesn't fan out over
    `type` has to say in its description that image, video, and news results are missing.
    """
    return f"{description} Covers web search only."


# Each schema maps to a single Search Analytics query with a fixed dimension set.
# Primary key is always (date + dimensions) to allow merge-mode dedupe across re-syncs.
#
# Sampling note: Google's Search Analytics API caps results at ~50,000 rows per
# (property, date, dimension-set, search type). When the cap is hit, rows are sorted
# by clicks descending and the tail is silently dropped. Schemas with more dimensions
# hit the cap faster (see `search_analytics_by_query_page` below). For full-fidelity
# data on high-traffic properties, the official BigQuery bulk export is the only
# escape hatch; see `google_search_console.py` for the full breakdown.
SEARCH_ANALYTICS_SCHEMAS: dict[str, SearchAnalyticsSchema] = {
    "search_analytics_by_date": {
        "dimensions": ["date"],
        "primary_key": ["date"],
        "should_sync_default": False,
        "description": _web_only("Daily totals for clicks, impressions, CTR, and average position."),
    },
    "search_analytics_by_query": {
        "dimensions": ["date", "query"],
        "primary_key": ["date", "query"],
        "should_sync_default": False,
        "description": _web_only(
            "Daily performance broken out by search query (keyword). "
            "Sites with >50K distinct queries/day will lose long-tail keywords to API sampling."
        ),
    },
    "search_analytics_by_page": {
        "dimensions": ["date", "page"],
        "primary_key": ["date", "page"],
        "should_sync_default": False,
        "description": _web_only(
            "Daily performance broken out by landing page URL. "
            "Sites with >50K distinct landing pages/day will lose long-tail URLs to API sampling."
        ),
    },
    "search_analytics_by_country": {
        "dimensions": ["date", "country"],
        "primary_key": ["date", "country"],
        "should_sync_default": False,
        "description": _web_only("Daily performance broken out by country (ISO 3166-1 alpha-3)."),
    },
    "search_analytics_by_device": {
        "dimensions": ["date", "device"],
        "primary_key": ["date", "device"],
        "should_sync_default": False,
        "description": _web_only("Daily performance broken out by device (DESKTOP, MOBILE, TABLET)."),
    },
    "search_analytics_by_country_device": {
        "dimensions": ["date", "country", "device"],
        "primary_key": ["date", "country", "device"],
        "should_sync_default": False,
        "description": _web_only(
            "Daily performance broken out by country and device together. Low cardinality "
            "(countries x three device types), so it stays well under the row sampling cap."
        ),
    },
    "search_analytics_by_query_country": {
        "dimensions": ["date", "query", "country"],
        "primary_key": ["date", "query", "country"],
        "should_sync_default": False,
        "description": _web_only(
            "Daily performance broken out by search query and the searcher's country. "
            "Multiplies query cardinality by the countries you rank in, so more of the "
            "long tail is lost to API sampling than in the per-query table."
        ),
    },
    "search_analytics_by_query_device": {
        "dimensions": ["date", "query", "device"],
        "primary_key": ["date", "query", "device"],
        "should_sync_default": False,
        "description": _web_only(
            "Daily performance broken out by search query and device. Up to three rows per "
            "query per day, so more of the long tail is lost to API sampling than in the "
            "per-query table."
        ),
    },
    "search_analytics_by_page_country": {
        "dimensions": ["date", "page", "country"],
        "primary_key": ["date", "page", "country"],
        "should_sync_default": False,
        "description": _web_only(
            "Daily performance broken out by landing page and the searcher's country. "
            "Multiplies page cardinality by the countries you rank in, so more of the "
            "long tail is lost to API sampling than in the per-page table."
        ),
    },
    "search_analytics_by_page_device": {
        "dimensions": ["date", "page", "device"],
        "primary_key": ["date", "page", "device"],
        "should_sync_default": False,
        "description": _web_only(
            "Daily performance broken out by landing page and device, for questions like "
            "mobile CTR per landing page. Up to three rows per page per day, so more of the "
            "long tail is lost to API sampling than in the per-page table."
        ),
    },
    "search_analytics_by_page_country_device": {
        "dimensions": ["date", "page", "country", "device"],
        "primary_key": ["date", "page", "country", "device"],
        "should_sync_default": False,
        "description": _web_only(
            "Daily performance broken out by landing page, country, and device. The most "
            "granular geo and device cut, and the one most exposed to Google's ~50K row per "
            "day cap: above it only the top rows by clicks come back and the rest are dropped "
            "silently. Prefer the two-dimension tables unless you need all three together."
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
        "description": _web_only(
            "Hourly totals for clicks, impressions, CTR, and average position. Google only "
            "keeps 10 days of hourly data, and the most recent hours are partial until they "
            "settle, so recent rows can change between syncs."
        ),
        "data_state": "hourly_all",
        "history_days": 10,
        "end_lag_days": 0,
        "ignore_incremental_watermark": True,
    },
    "search_analytics_by_query_page": {
        "dimensions": ["date", "query", "page"],
        "primary_key": ["date", "query", "page"],
        "should_sync_default": True,
        "description": _web_only(
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
        "description": _web_only(
            "Daily performance broken out by Google search result presentation type "
            "(e.g. RICH_RESULT, REVIEW_SNIPPET, FAQ_RICH_RESULT, VIDEO, AMP_BLUE_LINK). "
            "Useful for measuring the impact of structured data and rich result eligibility."
        ),
    },
    # These fan out over `type` instead of taking Google's web-only default, so each one costs a
    # request per search type per day. `search_type` is not a Google dimension: the iterator
    # queries one type at a time and stamps the row (see `_row_to_dict`).
    "search_analytics_by_search_type": {
        "dimensions": ["date"],
        "primary_key": ["date", "search_type"],
        "should_sync_default": False,
        "description": (
            "Daily totals split by search type: web, image, video, and news. Every other table "
            "covers web search only, so this is where image, video, and news traffic shows up."
        ),
        "search_types": SEARCH_TYPE_TABS,
    },
    "search_analytics_by_query_search_type": {
        "dimensions": ["date", "query"],
        "primary_key": ["date", "search_type", "query"],
        "should_sync_default": False,
        "description": (
            "Daily performance broken out by search query and search type (web, image, video, "
            "news). The ~50K row per day cap applies to each search type separately."
        ),
        "search_types": SEARCH_TYPE_TABS,
    },
    "search_analytics_by_page_search_type": {
        "dimensions": ["date", "page"],
        "primary_key": ["date", "search_type", "page"],
        "should_sync_default": False,
        "description": (
            "Daily performance broken out by landing page and search type (web, image, video, "
            "news). The ~50K row per day cap applies to each search type separately."
        ),
        "search_types": SEARCH_TYPE_TABS,
    },
}


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
