from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.similarweb.com"

# Similarweb's legacy REST API versions each resource in its own URL path segment (`/v1/...`,
# `/v4/...`) and carries the key in the `api_key` query param. This is the wire the source has
# always spoken, so it stays the behaviour of a source pinned to the framework's unversioned label.
API_VERSION_LEGACY = UNVERSIONED_API_VERSION
# API V5 replaces the per-resource paths with one `/v5/website-analysis` host, `api-key` header
# auth, and a standardized `{"meta": ..., "data": [...]}` envelope; metrics are selected with a
# `metrics` query param rather than a per-metric path.
API_VERSION_V5 = "v5"

# V5 serves every engagement metric from this one multi-metric endpoint. Each per-metric table
# requests only its own metric so the table set stays identical across versions.
V5_ENGAGEMENT_PATH = "/v5/website-analysis/websites/traffic-and-engagement"
# Free endpoint (no data credits) that reports the account's remaining credits and data access,
# so credential validation costs the customer nothing.
CAPABILITIES_PATH = "/capabilities"

# Every domain costs one request (and at least one data credit) per table per sync, so an
# unbounded list turns a single sync into an unbounded spend against the customer's credit pool.
MAX_DOMAINS = 50

# Rows per yielded chunk once a table's rows have been collected and ordered.
CHUNK_ROWS = 5000

# Results per page on the offset-paginated endpoints.
PAGE_LIMIT = 100

DEFAULT_COUNTRY = "world"
# V5 documents the worldwide breakdown as `ww`, where the legacy API used `world`; the sentinel is
# translated only on the V5 request wire, so stored rows keep the configured `world` value.
V5_WORLDWIDE_COUNTRY = "ww"

GRANULARITY_OPTIONS = (
    ("monthly", "Monthly"),
    ("weekly", "Weekly"),
    ("daily", "Daily"),
)

VISITS = "visits"
PAGE_VIEWS = "page_views"
PAGES_PER_VISIT = "pages_per_visit"
AVERAGE_VISIT_DURATION = "average_visit_duration"
BOUNCE_RATE = "bounce_rate"
GLOBAL_RANK = "global_rank"
TRAFFIC_SOURCES = "traffic_sources"
TRAFFIC_BY_COUNTRY = "traffic_by_country"


@frozen
class SimilarwebEndpointConfig:
    name: str
    # `{domain}` is substituted with each configured domain.
    path: str
    # Body key holding the endpoint's payload (Similarweb names it after the metric).
    data_key: str
    primary_keys: list[str]
    description: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # `date` is the period the row measures and never moves once published, so partitions
    # don't rewrite on later syncs. `None` for tables whose rows carry no period.
    partition_key: str | None = "date"
    # Whether the endpoint accepts the `country` / `granularity` filters. Rank and geo
    # breakdown endpoints take neither.
    accepts_country: bool = True
    accepts_granularity: bool = True
    # Offset-paginated (`limit`/`offset`) rather than a single full-window response.
    paginated: bool = False
    # The metric name to request from the V5 multi-metric engagement endpoint. Set only on the
    # engagement tables whose V5 wire is documented; `None` keeps the endpoint on its legacy path
    # under every pin (its V5 response shape isn't documented in enough detail to implement).
    v5_metric: str | None = None


_ENGAGEMENT_PATH = "/v1/website/{domain}/total-traffic-and-engagement"

SIMILARWEB_ENDPOINTS: dict[str, SimilarwebEndpointConfig] = {
    VISITS: SimilarwebEndpointConfig(
        name=VISITS,
        path=f"{_ENGAGEMENT_PATH}/visits",
        data_key="visits",
        primary_keys=["domain", "country", "granularity", "date"],
        description="Estimated desktop and mobile web visits per period for each configured domain",
        incremental_fields=[incremental_field("date")],
        v5_metric="visits",
    ),
    PAGE_VIEWS: SimilarwebEndpointConfig(
        name=PAGE_VIEWS,
        path=f"{_ENGAGEMENT_PATH}/page-views",
        # Similarweb returns this series under `pages_views`, not `page_views`.
        data_key="pages_views",
        primary_keys=["domain", "country", "granularity", "date"],
        description="Estimated desktop and mobile web page views per period for each configured domain",
        incremental_fields=[incremental_field("date")],
        v5_metric="page_views",
    ),
    PAGES_PER_VISIT: SimilarwebEndpointConfig(
        name=PAGES_PER_VISIT,
        path=f"{_ENGAGEMENT_PATH}/pages-per-visit",
        data_key="pages_per_visit",
        primary_keys=["domain", "country", "granularity", "date"],
        description="Average number of pages viewed per visit, per period, for each configured domain",
        incremental_fields=[incremental_field("date")],
        v5_metric="pages_per_visit",
    ),
    AVERAGE_VISIT_DURATION: SimilarwebEndpointConfig(
        name=AVERAGE_VISIT_DURATION,
        path=f"{_ENGAGEMENT_PATH}/average-visit-duration",
        data_key="average_visit_duration",
        primary_keys=["domain", "country", "granularity", "date"],
        description="Average visit duration in seconds, per period, for each configured domain",
        incremental_fields=[incremental_field("date")],
        v5_metric="average_visit_duration",
    ),
    BOUNCE_RATE: SimilarwebEndpointConfig(
        name=BOUNCE_RATE,
        path=f"{_ENGAGEMENT_PATH}/bounce-rate",
        data_key="bounce_rate",
        primary_keys=["domain", "country", "granularity", "date"],
        description="Share of visits that ended without further interaction, per period, for each configured domain",
        incremental_fields=[incremental_field("date")],
        v5_metric="bounce_rate",
    ),
    GLOBAL_RANK: SimilarwebEndpointConfig(
        name=GLOBAL_RANK,
        path="/v1/website/{domain}/global-rank/global-rank",
        data_key="global_rank",
        primary_keys=["domain", "date"],
        description="Monthly worldwide traffic rank for each configured domain",
        incremental_fields=[incremental_field("date")],
        # The rank endpoint is worldwide and monthly only; it takes neither filter.
        accepts_country=False,
        accepts_granularity=False,
    ),
    TRAFFIC_SOURCES: SimilarwebEndpointConfig(
        name=TRAFFIC_SOURCES,
        path="/v1/website/{domain}/traffic-sources/overview-share",
        data_key="visits",
        primary_keys=["domain", "country", "granularity", "source_type", "date"],
        description="Visits split by marketing channel and organic/paid, per period, for each configured domain",
        incremental_fields=[incremental_field("date")],
    ),
    TRAFFIC_BY_COUNTRY: SimilarwebEndpointConfig(
        name=TRAFFIC_BY_COUNTRY,
        path="/v4/website/{domain}/geo/total-traffic-by-country",
        data_key="records",
        primary_keys=["domain", "country"],
        description="Traffic share and engagement per visitor country, aggregated over the synced window",
        # Rows aggregate the whole requested window and carry no period column, so there is
        # nothing to advance a cursor on: full refresh only.
        partition_key=None,
        accepts_country=False,
        accepts_granularity=False,
        paginated=True,
    ),
}

ENDPOINTS = tuple(SIMILARWEB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SIMILARWEB_ENDPOINTS.items()
}
