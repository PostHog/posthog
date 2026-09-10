from dataclasses import field
from enum import Enum

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


class PaginationStyle(Enum):
    # Browse endpoint returns an opaque `cursor` token; absence of the token signals end of index.
    CURSOR = "cursor"
    # Search endpoints (synonyms/rules) and `GET /1/indexes` use 0-based `page` numbers.
    PAGE = "page"
    # Analytics and A/B testing endpoints page via `offset`/`limit`.
    OFFSET = "offset"


class AlgoliaApi(Enum):
    # Search API, served per-application at `{application_id}.algolia.net`.
    SEARCH = "search"
    # Analytics and A/B Testing APIs, served at `analytics.{region}.algolia.com`.
    ANALYTICS = "analytics"


@frozen
class AlgoliaEndpointConfig:
    name: str
    # Path on the Algolia REST API. `{index}` is substituted with the configured index name; for
    # analytics endpoints the index travels as an `index` query param instead (no `{index}` in path).
    path: str
    method: str
    pagination: PaginationStyle
    # Key in the JSON response that holds the list of rows (`hits`, `items`, `searches`, `abtests`).
    data_selector: str
    primary_keys: list[str] = field(default_factory=lambda: ["objectID"])
    # Whether the endpoint targets a specific index (so it needs the `index_name` field).
    requires_index: bool = True
    should_sync_default: bool = True
    # Rows requested per page (`hitsPerPage` for search, `limit` for analytics). Algolia caps both at 1000.
    page_size: int = 1000
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Which Algolia API (and therefore which host) serves this endpoint.
    api: AlgoliaApi = AlgoliaApi.SEARCH
    # Request click/conversion metrics alongside the base analytics table (analytics endpoints only).
    click_analytics: bool = False


# All Algolia endpoints below are full-refresh: the index browse endpoint and the
# synonyms/rules search endpoints expose no server-side "updated since" filter, so an
# incremental sync would still page the whole resource. The cursor (browse) and page
# (search/list) tokens make every endpoint resumable, so a heartbeat timeout picks back
# up where it left off rather than restarting.
ALGOLIA_ENDPOINTS: dict[str, AlgoliaEndpointConfig] = {
    "records": AlgoliaEndpointConfig(
        name="records",
        path="/1/indexes/{index}/browse",
        method="POST",
        pagination=PaginationStyle.CURSOR,
        data_selector="hits",
        primary_keys=["objectID"],
    ),
    "synonyms": AlgoliaEndpointConfig(
        name="synonyms",
        path="/1/indexes/{index}/synonyms/search",
        method="POST",
        pagination=PaginationStyle.PAGE,
        data_selector="hits",
        primary_keys=["objectID"],
        should_sync_default=False,
    ),
    "rules": AlgoliaEndpointConfig(
        name="rules",
        path="/1/indexes/{index}/rules/search",
        method="POST",
        pagination=PaginationStyle.PAGE,
        data_selector="hits",
        primary_keys=["objectID"],
        should_sync_default=False,
    ),
    "indices": AlgoliaEndpointConfig(
        name="indices",
        path="/1/indexes",
        method="GET",
        pagination=PaginationStyle.PAGE,
        data_selector="items",
        primary_keys=["name"],
        requires_index=False,
        should_sync_default=False,
    ),
    # Analytics API — aggregate metrics for the configured index over Algolia's default recent
    # window (no server-side "updated since" filter, so each sync replaces the snapshot).
    "top_searches": AlgoliaEndpointConfig(
        name="top_searches",
        path="/2/searches",
        method="GET",
        pagination=PaginationStyle.OFFSET,
        data_selector="searches",
        primary_keys=["search"],
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
        click_analytics=True,
    ),
    "top_hits": AlgoliaEndpointConfig(
        name="top_hits",
        path="/2/hits",
        method="GET",
        pagination=PaginationStyle.OFFSET,
        data_selector="hits",
        primary_keys=["hit"],
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
        click_analytics=True,
    ),
    "searches_no_results": AlgoliaEndpointConfig(
        name="searches_no_results",
        path="/2/searches/noResults",
        method="GET",
        pagination=PaginationStyle.OFFSET,
        data_selector="searches",
        primary_keys=["search"],
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
    ),
    "searches_no_clicks": AlgoliaEndpointConfig(
        name="searches_no_clicks",
        path="/2/searches/noClicks",
        method="GET",
        pagination=PaginationStyle.OFFSET,
        data_selector="searches",
        primary_keys=["search"],
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
    ),
    # A/B Testing API v3 (`/3/abtests`). The v2 `/2/abtests` listing is deprecated in favour of this;
    # each row carries the test definition and its per-variant results. Application-level (no index).
    "ab_tests": AlgoliaEndpointConfig(
        name="ab_tests",
        path="/3/abtests",
        method="GET",
        pagination=PaginationStyle.OFFSET,
        data_selector="abtests",
        primary_keys=["abTestID"],
        requires_index=False,
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
    ),
}

ENDPOINTS = tuple(ALGOLIA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ALGOLIA_ENDPOINTS.items()
}
