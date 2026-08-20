from dataclasses import dataclass, field

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
}

ENDPOINTS = tuple(TRUSTPILOT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TRUSTPILOT_ENDPOINTS.items()
}
