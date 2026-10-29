from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.trustpilot.com/v1"
TOKEN_URL = "https://api.trustpilot.com/v1/oauth/oauth-business-users-for-applications/accesstoken"

# Trustpilot's review list endpoints accept up to 100 rows per page (default 20); request the max
# to minimise round trips.
PER_PAGE = 100

# The page-numbered review endpoints are documented as "limited to 100,000 records" per query, so
# with PER_PAGE=100 there is nothing past page 1,000. Incremental syncs keep each query window
# small; only the initial backfill of a very large account can reach this cap.
MAX_PAGES = 1000

# The catalog products endpoint documents a perPage cap of 1000 (default 100).
CATALOG_PER_PAGE = 1000


@dataclass(frozen=True)
class TrustpilotEndpointConfig:
    name: str
    # Path under /v1 with a {business_unit_id} placeholder.
    path: str
    # Key wrapping the row list in the JSON response; None means the whole body is a single row.
    response_key: str | None
    # Private endpoints need a client-credentials OAuth bearer; public ones take the `apikey` header.
    requires_oauth: bool
    paginated: bool = True
    # Explicit stable sort so page boundaries can't skip or duplicate rows as new reviews arrive
    # mid-sync. Only the service reviews endpoint documents `orderBy`.
    order_by: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field to partition by.
    partition_key: str | None = None
    # None for endpoints that document no perPage param.
    per_page: int | None = PER_PAGE
    # Only the review list endpoints document the 100,000-record query cap.
    max_pages: int | None = MAX_PAGES
    params: dict[str, Any] = field(default_factory=dict)
    # Set for endpoints read one row at a time, keyed by an ID from a parent endpoint's rows.
    fanout: DependentEndpointConfig | None = None

    # `default_incremental_field` and `page_size` satisfy the shared fan-out helper's protocol.
    @property
    def default_incremental_field(self) -> str | None:
        return None

    @property
    def page_size(self) -> int:
        return self.per_page or PER_PAGE


TRUSTPILOT_ENDPOINTS: dict[str, TrustpilotEndpointConfig] = {
    "business_unit": TrustpilotEndpointConfig(
        name="business_unit",
        path="/business-units/{business_unit_id}",
        response_key=None,
        requires_oauth=False,
        paginated=False,
    ),
    "service_reviews": TrustpilotEndpointConfig(
        name="service_reviews",
        path="/private/business-units/{business_unit_id}/reviews",
        response_key="reviews",
        requires_oauth=True,
        order_by="createdat.asc",
        # `startDateTime` is the endpoint's only server-side time filter and it keys off the
        # review's creation time, so `createdAt` is the one honest incremental cursor. Edits to an
        # already-synced review only land once a full refresh re-reads it.
        incremental_fields=[
            {
                "label": "createdAt",
                "type": IncrementalFieldType.DateTime,
                "field": "createdAt",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_key="createdAt",
    ),
    "product_reviews": TrustpilotEndpointConfig(
        name="product_reviews",
        path="/private/product-reviews/business-units/{business_unit_id}/reviews",
        response_key="productReviews",
        requires_oauth=True,
        # No documented server-side time filter, so this endpoint is full refresh only.
        partition_key="createdAt",
    ),
    "product_review_summaries": TrustpilotEndpointConfig(
        name="product_review_summaries",
        path="/private/product-reviews/business-units/{business_unit_id}/summaries",
        response_key="summaries",
        requires_oauth=True,
        max_pages=None,
        # One summary per product SKU.
        primary_keys=["sku"],
    ),
    "catalog_products": TrustpilotEndpointConfig(
        name="catalog_products",
        path="/private/business-units/{business_unit_id}/catalog/products",
        response_key="products",
        requires_oauth=True,
        per_page=CATALOG_PER_PAGE,
        max_pages=None,
        params={
            "sortBy": "createdAt",
            "sortOrder": "asc",
            # Return every stored locale and market, not only the default one, so variant content
            # and prices are complete.
            "returnAllLocales": "true",
            "returnAllMarkets": "true",
            "includeMatchingProductCount": "false",
        },
        primary_keys=["productId"],
    ),
    "locations": TrustpilotEndpointConfig(
        name="locations",
        path="/private/business-units/{business_unit_id}/locations",
        response_key="locations",
        requires_oauth=True,
        per_page=None,
        max_pages=None,
    ),
    "product_review_conversations": TrustpilotEndpointConfig(
        name="product_review_conversations",
        path="/private/conversations/{conversation_id}",
        response_key=None,
        requires_oauth=True,
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="product_reviews",
            resolve_param="conversation_id",
            resolve_field="conversationId",
            include_from_parent=[],
            parent_params={"perPage": PER_PAGE},
            # A conversation removed between the review listing and this fetch must not fail the sync.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(TRUSTPILOT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TRUSTPILOT_ENDPOINTS.items()
}
