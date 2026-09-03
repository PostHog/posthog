from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://ssl.bing.com/webmaster/api.svc/json"

# Every stats row carries `date`, parsed from the API's WCF-serialized `Date` field. The API has no
# server-side time filter (each call returns the full ~6-month window Bing retains), so `date` is
# declared as an incremental field purely to enable the merge sync method: refetched rows dedupe on
# the primary key while rows Bing has already expired stay in the warehouse, accumulating history
# beyond the vendor's retention.
_DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "date",
        "type": IncrementalFieldType.Date,
        "field": "date",
        "field_type": IncrementalFieldType.Date,
    },
]


@dataclass
class BingWebmasterToolsEndpoint:
    # JSON API operation name, e.g. "GetQueryStats" (https://ssl.bing.com/webmaster/api.svc/json/{method}).
    method: str
    primary_keys: list[str]
    # Per-site endpoints take a `siteUrl` param and are fanned out over every selected verified site,
    # with each row stamped with `site_url` (which is why it leads the primary key).
    per_site: bool = True
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_DATE_INCREMENTAL_FIELDS))
    should_sync_default: bool = True
    description: str | None = None


ENDPOINT_CONFIGS: dict[str, BingWebmasterToolsEndpoint] = {
    "sites": BingWebmasterToolsEndpoint(
        method="GetUserSites",
        primary_keys=["url"],
        per_site=False,
        incremental_fields=[],
        description="Every site registered on the connected Bing Webmaster Tools account, with its verification status.",
    ),
    "query_stats": BingWebmasterToolsEndpoint(
        method="GetQueryStats",
        primary_keys=["site_url", "date", "query"],
        description=(
            "Traffic statistics for the site's top search queries: impressions, clicks, and average "
            "positions. Bing updates this data weekly and retains about six months."
        ),
    ),
    "page_stats": BingWebmasterToolsEndpoint(
        method="GetPageStats",
        primary_keys=["site_url", "date", "query"],
        description=(
            "Traffic statistics for the site's top pages: impressions, clicks, and average positions. "
            "The page URL is in the query column. Bing updates this data weekly and retains about six months."
        ),
    ),
    "rank_and_traffic_stats": BingWebmasterToolsEndpoint(
        method="GetRankAndTrafficStats",
        primary_keys=["site_url", "date"],
        description=(
            "Daily impressions and clicks for the site across Bing search verticals. "
            "Bing updates this data daily and retains about six months."
        ),
    ),
    "crawl_stats": BingWebmasterToolsEndpoint(
        method="GetCrawlStats",
        primary_keys=["site_url", "date"],
        description=(
            "Daily Bingbot crawl activity for the site: pages crawled, crawl errors, HTTP status code "
            "counts, and pages in the index. Bing retains about six months."
        ),
    ),
}

ENDPOINTS = tuple(ENDPOINT_CONFIGS.keys())
