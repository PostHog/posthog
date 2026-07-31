from dataclasses import dataclass, field


@dataclass
class BluetallyEndpointConfig:
    path: str
    # BlueTally IDs are globally unique integers per resource, so `id` alone is a safe key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp used for datetime partitioning (never `updated_at`, which churns).
    partition_key: str | None = "created_at"
    # Column to sort by while paginating. Every list endpoint accepts `created_at`; sorting on it
    # ascending keeps offset pagination stable even as new rows are appended mid-sync.
    sort: str = "created_at"


# Core IT-asset-management resources exposed by BlueTally's REST API. Every one is a plain
# `GET /<resource>` list endpoint returning a bare JSON array with limit/offset pagination, an
# integer `id`, and `created_at`/`updated_at` timestamps. The API has no server-side
# `updated_after`-style filter, so all of these sync as full refresh (see source.py / get_schemas).
BLUETALLY_ENDPOINTS: dict[str, BluetallyEndpointConfig] = {
    "assets": BluetallyEndpointConfig(path="/assets"),
    "accessories": BluetallyEndpointConfig(path="/accessories"),
    "components": BluetallyEndpointConfig(path="/components"),
    "consumables": BluetallyEndpointConfig(path="/consumables"),
    "licenses": BluetallyEndpointConfig(path="/licenses"),
    "employees": BluetallyEndpointConfig(path="/employees"),
    "products": BluetallyEndpointConfig(path="/products"),
    "categories": BluetallyEndpointConfig(path="/categories"),
    "manufacturers": BluetallyEndpointConfig(path="/manufacturers"),
    "suppliers": BluetallyEndpointConfig(path="/suppliers"),
    "locations": BluetallyEndpointConfig(path="/locations"),
    "departments": BluetallyEndpointConfig(path="/departments"),
    "statuses": BluetallyEndpointConfig(path="/statuses"),
    "depreciations": BluetallyEndpointConfig(path="/depreciations"),
    "maintenances": BluetallyEndpointConfig(path="/maintenances"),
    "audits": BluetallyEndpointConfig(path="/audits"),
}

ENDPOINTS = tuple(BLUETALLY_ENDPOINTS.keys())
