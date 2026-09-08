from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.mn.co/admin/v1"

# Mighty Networks caps `per_page` at 100 (default 25). Always request the max to minimise round trips.
PER_PAGE = 100

ENDPOINTS = (
    "Members",
    "Spaces",
    "Posts",
    "Events",
    "Plans",
    "Subscriptions",
    "Purchases",
    "Tags",
    "Badges",
)

# Path under /admin/v1/networks/{network_id}.
PATHS: dict[str, str] = {
    "Members": "/members",
    "Spaces": "/spaces",
    "Posts": "/posts",
    "Events": "/events",
    "Plans": "/plans",
    "Subscriptions": "/subscriptions",
    "Purchases": "/purchases",
    "Tags": "/tags",
    "Badges": "/badges",
}

# Subscriptions and Purchases nest the record's real id under a `subscription`/`purchase` object
# rather than exposing it at the row root (see mighty_networks.py's flatten helpers), everything
# else has a flat `id`.
PRIMARY_KEYS: dict[str, list[str]] = {name: ["id"] for name in ENDPOINTS}

# All endpoints expose created_at, and it never changes after creation, unlike updated_at.
PARTITION_FIELDS: dict[str, str] = dict.fromkeys(ENDPOINTS, "created_at")

# No list endpoint documents or accepts an updated_since/created_since filter (checked against the
# published OpenAPI spec at api.mn.co/admin/v1/spec.json and docs.mightynetworks.com/admin-api) —
# every endpoint is full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
