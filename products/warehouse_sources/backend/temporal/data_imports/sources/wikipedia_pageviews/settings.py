from dataclasses import dataclass, field
from datetime import date

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://wikimedia.org/api/rest_v1/metrics"

# Wikimedia policy requires a descriptive User-Agent; clients without one are throttled to a
# fraction of the normal per-minute request budget.
USER_AGENT = "PostHog Data Warehouse (https://posthog.com; support@posthog.com)"

# Pageview data begins 2015-07-01; earlier windows always 404.
DATA_START_DATE = date(2015, 7, 1)

# Days per aggregate/per-article request. The API accepts arbitrary ranges in the URL path;
# chunking keeps responses bounded and gives us resume checkpoints.
WINDOW_DAYS = 366
# The top endpoint serves one day per request; batch this many days per yield/checkpoint.
TOP_WINDOW_DAYS = 7

# Each article title costs one request per window, so an unbounded list fans out into an
# unbounded number of outbound requests. Cap the number of titles synced per source.
MAX_ARTICLES = 100
# Same fan-out bound for the per-country top pages table: one request per country per day.
MAX_COUNTRIES = 10

# The per-country top pages dataset begins 2021-01-01; earlier days always 404.
COUNTRY_TOP_ARTICLES_START_DATE = date(2021, 1, 1)

PAGEVIEWS_ENDPOINT = "pageviews"
ARTICLE_PAGEVIEWS_ENDPOINT = "article_pageviews"
TOP_ARTICLES_ENDPOINT = "top_articles"
COUNTRY_PAGEVIEWS_ENDPOINT = "country_pageviews"
COUNTRY_TOP_ARTICLES_ENDPOINT = "country_top_articles"
UNIQUE_DEVICES_ENDPOINT = "unique_devices"
MEDIA_REQUESTS_ENDPOINT = "media_requests"

ACCESS_OPTIONS = (
    ("all-access", "All access methods"),
    ("desktop", "Desktop"),
    ("mobile-app", "Mobile app"),
    ("mobile-web", "Mobile web"),
)

AGENT_OPTIONS = (
    ("user", "User (human traffic)"),
    ("all-agents", "All agents"),
    ("spider", "Spider (crawlers)"),
    ("automated", "Automated (bots)"),
)

# The unique devices API splits by site rather than by access method and has no app split, so
# the table syncs every site split instead of mapping the access setting.
UNIQUE_DEVICES_ACCESS_SITES = ("all-sites", "desktop-site", "mobile-site")

# One series per media type keeps the media type split in the table.
MEDIA_TYPES = ("image", "video", "audio", "document", "other")
# Agent types the media requests API accepts; other agent settings fall back to all-agents.
MEDIA_REQUEST_AGENTS = ("user", "spider", "all-agents")


@dataclass
class WikipediaPageviewsEndpointConfig:
    name: str
    primary_keys: list[str]
    description: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # `date` is derived from the API's day identifier, which never changes for a given row —
    # stable, so partitions don't rewrite on later syncs.
    partition_key: str = "date"


WIKIPEDIA_PAGEVIEWS_ENDPOINTS: dict[str, WikipediaPageviewsEndpointConfig] = {
    PAGEVIEWS_ENDPOINT: WikipediaPageviewsEndpointConfig(
        name=PAGEVIEWS_ENDPOINT,
        primary_keys=["project", "access", "agent", "timestamp"],
        description="Daily total pageviews for the whole project",
        incremental_fields=[incremental_field("date")],
    ),
    ARTICLE_PAGEVIEWS_ENDPOINT: WikipediaPageviewsEndpointConfig(
        name=ARTICLE_PAGEVIEWS_ENDPOINT,
        primary_keys=["project", "access", "agent", "article", "timestamp"],
        description="Daily pageviews per configured article title",
        incremental_fields=[incremental_field("date")],
    ),
    TOP_ARTICLES_ENDPOINT: WikipediaPageviewsEndpointConfig(
        name=TOP_ARTICLES_ENDPOINT,
        primary_keys=["project", "access", "year", "month", "day", "article"],
        description="The 1000 most-viewed articles per day",
        incremental_fields=[incremental_field("date")],
    ),
    COUNTRY_PAGEVIEWS_ENDPOINT: WikipediaPageviewsEndpointConfig(
        name=COUNTRY_PAGEVIEWS_ENDPOINT,
        primary_keys=["project", "access", "year", "month", "country"],
        description="Monthly pageviews for the whole project, split by country",
        incremental_fields=[incremental_field("date")],
    ),
    COUNTRY_TOP_ARTICLES_ENDPOINT: WikipediaPageviewsEndpointConfig(
        name=COUNTRY_TOP_ARTICLES_ENDPOINT,
        # Ranks tie, and the ranking spans all Wikimedia projects, so project + article is the
        # unique key within a country's day.
        primary_keys=["country", "access", "year", "month", "day", "project", "article"],
        description="The most-viewed articles per day across all Wikimedia projects, for each configured country",
        incremental_fields=[incremental_field("date")],
    ),
    UNIQUE_DEVICES_ENDPOINT: WikipediaPageviewsEndpointConfig(
        name=UNIQUE_DEVICES_ENDPOINT,
        primary_keys=["project", "access_site", "timestamp"],
        description="Daily unique devices that visited the project, split by site",
        incremental_fields=[incremental_field("date")],
    ),
    MEDIA_REQUESTS_ENDPOINT: WikipediaPageviewsEndpointConfig(
        name=MEDIA_REQUESTS_ENDPOINT,
        primary_keys=["referer", "media_type", "agent", "timestamp"],
        description="Daily requests for media files referred by the project, split by media type",
        incremental_fields=[incremental_field("date")],
    ),
}

ENDPOINTS = tuple(WIKIPEDIA_PAGEVIEWS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in WIKIPEDIA_PAGEVIEWS_ENDPOINTS.items()
}
