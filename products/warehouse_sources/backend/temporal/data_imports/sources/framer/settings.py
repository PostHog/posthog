from products.warehouse_sources.backend.types import IncrementalField

ENDPOINTS = (
    "Project",
    "Pages",
    "Collections",
    "CollectionItems",
    "Locales",
    "Redirects",
    "Deployments",
    "LocalizationGroups",
    "UnpublishedPageChanges",
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
    "LocalizationGroups": ["id"],
    # A path can repeat when one page is removed and another takes its path, so key on the page node.
    "UnpublishedPageChanges": ["nodeId"],
}

# listDeployments serves at most 30 per page.
DEPLOYMENTS_PAGE_SIZE = 30
# Hard cap on deployment pages per sync so a pathological cursor loop can't spin forever.
DEPLOYMENTS_MAX_PAGES = 500

# listLocalizationGroupsNext returns one group per call. The cap bounds a cursor loop that
# never reports the end.
LOCALIZATION_GROUPS_MAX = 200_000
