from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

G2_API_VERSION = "v2"
G2_BASE_URL = "https://data.g2.com"
# G2 caps page[size] at 250 and defaults to 25.
PAGE_SIZE = 250


@frozen
class G2EndpointConfig:
    # Relative to /api/{version}. `{product_id}` is filled in from the source's product_id field.
    path: str
    primary_keys: list[str]
    requires_product_id: bool = False
    description: str | None = None


G2_ENDPOINTS: dict[str, G2EndpointConfig] = {
    "products": G2EndpointConfig(
        path="/products",
        primary_keys=["id"],
        description="G2's public catalog of software products.",
    ),
    "categories": G2EndpointConfig(
        path="/categories",
        primary_keys=["id"],
        description="G2's product category taxonomy.",
    ),
    "vendors": G2EndpointConfig(
        path="/vendors",
        primary_keys=["id"],
        description="Vendors (software companies) listed on G2.",
    ),
    "reviews": G2EndpointConfig(
        path="/products/{product_id}/reviews",
        primary_keys=["id"],
        requires_product_id=True,
        description="Published reviews for your G2 product.",
    ),
}

ENDPOINTS = tuple(G2_ENDPOINTS.keys())

# G2's OpenAPI spec documents no `sort` parameter and no guaranteed default order for any list
# endpoint, so a cursor watermark built from `filter[updated_at_gt]` couldn't be verified safe —
# every endpoint ships full refresh only, even though categories/vendors/reviews accept that filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
