from dataclasses import field
from enum import Enum

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class PaginationStyle(Enum):
    # Browse endpoint returns an opaque `cursor` token; absence of the token signals end of index.
    CURSOR = "cursor"
    # Search endpoints (synonyms/rules) and `GET /1/indexes` use 0-based `page` numbers.
    PAGE = "page"
    # Analytics and A/B testing endpoints page via `offset`/`limit`.
    OFFSET = "offset"
    # Analytics time-series and click-position endpoints answer the whole period at once.
    SINGLE = "single"


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
    primary_keys: list[str] | None = field(default_factory=lambda: ["objectID"])
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
    # Query param carrying the incremental cursor. None means the endpoint is full refresh.
    start_param: str | None = None
    # Set when the path takes a parameter resolved from another endpoint's rows.
    fanout: DependentEndpointConfig | None = None

    @property
    def default_incremental_field(self) -> str | None:
        return self.incremental_fields[0]["field"] if self.incremental_fields else None


# Algolia keeps attributing events to recent days after those days close, so an incremental sync
# re-reads a trailing window from the stored watermark and merges it back on `date`.
ANALYTICS_LOOKBACK_DAYS = 3

_DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [incremental_field("date", IncrementalFieldType.Date)]


# Everything without a `start_param` is full refresh, because no server-side "updated since"
# filter exists for it. Its page token still makes it resumable after a heartbeat timeout.
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
    # Analytics API time series: one row per day, filtered forward from `startDate`.
    "conversion_rate": AlgoliaEndpointConfig(
        name="conversion_rate",
        path="/2/conversions/conversionRate",
        method="GET",
        pagination=PaginationStyle.SINGLE,
        data_selector="dates",
        primary_keys=["date"],
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
        start_param="startDate",
        incremental_fields=_DATE_INCREMENTAL_FIELDS,
    ),
    "add_to_cart_rate": AlgoliaEndpointConfig(
        name="add_to_cart_rate",
        path="/2/conversions/addToCartRate",
        method="GET",
        pagination=PaginationStyle.SINGLE,
        data_selector="dates",
        primary_keys=["date"],
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
        start_param="startDate",
        incremental_fields=_DATE_INCREMENTAL_FIELDS,
    ),
    "purchase_rate": AlgoliaEndpointConfig(
        name="purchase_rate",
        path="/2/conversions/purchaseRate",
        method="GET",
        pagination=PaginationStyle.SINGLE,
        data_selector="dates",
        primary_keys=["date"],
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
        start_param="startDate",
        incremental_fields=_DATE_INCREMENTAL_FIELDS,
    ),
    "revenue": AlgoliaEndpointConfig(
        name="revenue",
        path="/2/conversions/revenue",
        method="GET",
        pagination=PaginationStyle.SINGLE,
        data_selector="dates",
        primary_keys=["date"],
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
        start_param="startDate",
        incremental_fields=_DATE_INCREMENTAL_FIELDS,
    ),
    "click_through_rate": AlgoliaEndpointConfig(
        name="click_through_rate",
        path="/2/clicks/clickThroughRate",
        method="GET",
        pagination=PaginationStyle.SINGLE,
        data_selector="dates",
        primary_keys=["date"],
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
        start_param="startDate",
        incremental_fields=_DATE_INCREMENTAL_FIELDS,
    ),
    "average_click_position": AlgoliaEndpointConfig(
        name="average_click_position",
        path="/2/clicks/averageClickPosition",
        method="GET",
        pagination=PaginationStyle.SINGLE,
        data_selector="dates",
        primary_keys=["date"],
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
        start_param="startDate",
        incremental_fields=_DATE_INCREMENTAL_FIELDS,
    ),
    "users_count": AlgoliaEndpointConfig(
        name="users_count",
        path="/2/users/count",
        method="GET",
        pagination=PaginationStyle.SINGLE,
        data_selector="dates",
        primary_keys=["date"],
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
        start_param="startDate",
        incremental_fields=_DATE_INCREMENTAL_FIELDS,
    ),
    # Analytics API breakdowns: a "top N over the period" snapshot with no date column.
    "top_filters": AlgoliaEndpointConfig(
        name="top_filters",
        path="/2/filters",
        method="GET",
        pagination=PaginationStyle.OFFSET,
        data_selector="attributes",
        primary_keys=["attribute"],
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
    ),
    "top_filter_values": AlgoliaEndpointConfig(
        name="top_filter_values",
        path="/2/filters/{attribute}",
        method="GET",
        pagination=PaginationStyle.OFFSET,
        data_selector="values",
        # Every child row repeats the attribute, so the key is unique table-wide, not per parent.
        primary_keys=["attribute", "operator", "value"],
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
        fanout=DependentEndpointConfig(
            parent_name="top_filters",
            resolve_param="attribute",
            resolve_field="attribute",
            include_from_parent=[],
        ),
    ),
    "top_countries": AlgoliaEndpointConfig(
        name="top_countries",
        path="/2/countries",
        method="GET",
        pagination=PaginationStyle.OFFSET,
        data_selector="countries",
        primary_keys=["country"],
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
    ),
    "click_positions": AlgoliaEndpointConfig(
        name="click_positions",
        path="/2/clicks/positions",
        method="GET",
        pagination=PaginationStyle.SINGLE,
        data_selector="positions",
        # A row's only identity is its `position` range, which arrives as a two-element array.
        primary_keys=None,
        should_sync_default=False,
        api=AlgoliaApi.ANALYTICS,
    ),
}

ENDPOINTS = tuple(ALGOLIA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ALGOLIA_ENDPOINTS.items()
}
