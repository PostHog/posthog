from dataclasses import dataclass
from typing import Optional

# Webflow Data API v2. The legacy v1 API was deprecated on 2025-03-31, so this
# source only ever talks to v2 (Bearer token + scopes).
WEBFLOW_BASE_URL = "https://api.webflow.com/v2"

# Max page size accepted by every paginated v2 list endpoint.
DEFAULT_PAGE_SIZE = 100

# Dynamically discovered CMS collections are exposed as one schema per collection,
# named "{prefix}{collection_slug}". The prefix lets source_for_pipeline tell a
# collection-items schema apart from a static endpoint and resolve it back to a
# collection id at sync time.
COLLECTION_SCHEMA_PREFIX = "collection_"

# Path template for a single collection's items (staged/draft items).
COLLECTION_ITEMS_PATH = "/collections/{collection_id}/items"


@dataclass
class WebflowEndpointConfig:
    name: str
    # Path appended to WEBFLOW_BASE_URL. May contain a "{site_id}" placeholder.
    path: str
    # Top-level key in the JSON envelope that holds the list of records. The
    # transport falls back to auto-detecting the first list-valued key when this
    # key is absent, so a wrong guess degrades gracefully rather than dropping rows.
    data_key: str
    primary_key: str = "id"
    # Stable, immutable datetime field used for partitioning. Never use a
    # "last updated"/"last seen" field here — partitions would rewrite every sync.
    partition_key: Optional[str] = None
    paginated: bool = True
    requires_site: bool = True
    # When set, the endpoint returns a single resource object (not a list envelope),
    # so the transport wraps it into a one-row page instead of looking for a list.
    single_object: bool = False
    # When set, the named nested object is merged up into the row root. Webflow's
    # products endpoint nests the product under a "product" key alongside "skus".
    flatten_key: Optional[str] = None
    # Explicit sort to keep offset pagination stable across a sync. Only set where
    # the endpoint is confirmed to accept it.
    sort_by: Optional[str] = None
    sort_order: str = "asc"


# Static, site-scoped endpoints. The CMS collection-items endpoints are added
# dynamically per site (see WebflowSource.get_schemas), because every site has a
# different set of collections.
WEBFLOW_ENDPOINTS: dict[str, WebflowEndpointConfig] = {
    # Site-scoped to the configured site_id. The account-wide /sites endpoint would
    # leak metadata for every other site a broadly scoped token can reach, so we hit
    # /sites/{site_id} (a single site object) instead.
    "sites": WebflowEndpointConfig(
        name="sites",
        path="/sites/{site_id}",
        data_key="sites",
        partition_key="createdOn",
        paginated=False,
        single_object=True,
    ),
    "collections": WebflowEndpointConfig(
        name="collections",
        path="/sites/{site_id}/collections",
        data_key="collections",
        partition_key="createdOn",
        paginated=False,
    ),
    "pages": WebflowEndpointConfig(
        name="pages",
        path="/sites/{site_id}/pages",
        data_key="pages",
        partition_key="createdOn",
    ),
    "products": WebflowEndpointConfig(
        name="products",
        path="/sites/{site_id}/products",
        data_key="items",
        partition_key="createdOn",
        flatten_key="product",
    ),
    "orders": WebflowEndpointConfig(
        name="orders",
        path="/sites/{site_id}/orders",
        data_key="orders",
        primary_key="orderId",
        partition_key="acceptedOn",
    ),
    "users": WebflowEndpointConfig(
        name="users",
        path="/sites/{site_id}/users",
        data_key="users",
        partition_key="createdOn",
    ),
    "forms": WebflowEndpointConfig(
        name="forms",
        path="/sites/{site_id}/forms",
        data_key="forms",
    ),
}

STATIC_ENDPOINTS = tuple(WEBFLOW_ENDPOINTS.keys())


def collection_items_endpoint_config(collection_id: str) -> WebflowEndpointConfig:
    """Build the endpoint config for a single CMS collection's items.

    Items are sorted by createdOn ascending so offset pagination stays stable —
    createdOn is immutable, so new items append to the end and don't shift pages
    that were already fetched mid-sync.
    """
    return WebflowEndpointConfig(
        name=f"{COLLECTION_SCHEMA_PREFIX}{collection_id}",
        path=COLLECTION_ITEMS_PATH.format(collection_id=collection_id),
        data_key="items",
        partition_key="createdOn",
        requires_site=False,
        sort_by="createdOn",
        sort_order="asc",
    )
