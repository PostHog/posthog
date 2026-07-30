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

PAGEVIEWS_ENDPOINT = "pageviews"
ARTICLE_PAGEVIEWS_ENDPOINT = "article_pageviews"
TOP_ARTICLES_ENDPOINT = "top_articles"

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
}

ENDPOINTS = tuple(WIKIPEDIA_PAGEVIEWS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in WIKIPEDIA_PAGEVIEWS_ENDPOINTS.items()
}
