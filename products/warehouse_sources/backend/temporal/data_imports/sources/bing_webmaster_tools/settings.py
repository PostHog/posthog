from typing import TypedDict

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class BingEndpoint(TypedDict):
    # Bing Webmaster API method name, e.g. `GetQueryStats`.
    method: str
    primary_key: list[str]
    should_sync_default: bool
    description: str


# Every stats endpoint carries a per-day `Date`, so the whole catalog partitions and
# increments on it. Bing exposes no server-side date filter — a call always returns the
# vendor's full retention window — so the incremental cursor only drives merge dedupe, not
# a narrower request (see `bing_webmaster_tools.py`).
DATE_INCREMENTAL_FIELD: IncrementalField = {
    "label": "Date",
    "field": "Date",
    "type": IncrementalFieldType.Date,
    "field_type": IncrementalFieldType.Date,
}


# Bing returns each table as a flat array under the JSON `"d"` node, with no pagination and
# no request-side date range. `GetQueryStats`/`GetPageStats` carry a `Date` per row, so the
# primary key is (Query, Date); the two daily aggregate tables key on `Date` alone.
ENDPOINTS: dict[str, BingEndpoint] = {
    "query_stats": {
        "method": "GetQueryStats",
        "primary_key": ["Query", "Date"],
        "should_sync_default": True,
        "description": (
            "Daily organic-search performance for the property's top queries: clicks, "
            "impressions, and average click and impression positions per query and day."
        ),
    },
    "page_stats": {
        "method": "GetPageStats",
        "primary_key": ["Query", "Date"],
        "should_sync_default": True,
        "description": (
            "Daily organic-search performance for the property's top pages: clicks, "
            "impressions, and average click and impression positions per landing page and day. "
            "The `Query` column holds the page URL, matching the Bing API response."
        ),
    },
    "rank_and_traffic_stats": {
        "method": "GetRankAndTrafficStats",
        "primary_key": ["Date"],
        "should_sync_default": True,
        "description": "Daily clicks and impressions totals for the property across Bing search.",
    },
    "crawl_stats": {
        "method": "GetCrawlStats",
        "primary_key": ["Date"],
        "should_sync_default": True,
        "description": (
            "Daily crawl statistics for the property: pages crawled, pages in the index, "
            "inbound links, crawl errors, and a breakdown of HTTP response codes Bing saw."
        ),
    },
}
