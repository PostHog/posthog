from products.warehouse_sources.backend.types import IncrementalField

ENDPOINTS = (
    "Project",
    "Pages",
    "Collections",
    "CollectionItems",
    "Locales",
    "Redirects",
    "Deployments",
)

# The Server API returns each dataset in full per RPC call, with no server-side time
# filter to resume from — every endpoint is full-refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}

PRIMARY_KEYS: dict[str, list[str]] = {
    "Project": ["id"],
    "Pages": ["id"],
    "Collections": ["id"],
    # Item ids are only documented unique within their collection.
    "CollectionItems": ["collectionId", "id"],
    "Locales": ["id"],
    "Redirects": ["id"],
    "Deployments": ["id"],
}

# listDeployments serves at most 30 per page.
DEPLOYMENTS_PAGE_SIZE = 30
# Hard cap on deployment pages per sync so a pathological cursor loop can't spin forever.
DEPLOYMENTS_MAX_PAGES = 500
