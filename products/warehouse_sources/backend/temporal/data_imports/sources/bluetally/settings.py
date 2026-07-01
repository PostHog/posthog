from dataclasses import dataclass, field


@dataclass
class BluetallyEndpointConfig:
    name: str
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
    "assets": BluetallyEndpointConfig(name="assets", path="/assets"),
    "accessories": BluetallyEndpointConfig(name="accessories", path="/accessories"),
    "components": BluetallyEndpointConfig(name="components", path="/components"),
    "consumables": BluetallyEndpointConfig(name="consumables", path="/consumables"),
    "licenses": BluetallyEndpointConfig(name="licenses", path="/licenses"),
    "employees": BluetallyEndpointConfig(name="employees", path="/employees"),
    "products": BluetallyEndpointConfig(name="products", path="/products"),
    "categories": BluetallyEndpointConfig(name="categories", path="/categories"),
    "manufacturers": BluetallyEndpointConfig(name="manufacturers", path="/manufacturers"),
    "suppliers": BluetallyEndpointConfig(name="suppliers", path="/suppliers"),
    "locations": BluetallyEndpointConfig(name="locations", path="/locations"),
    "departments": BluetallyEndpointConfig(name="departments", path="/departments"),
    "statuses": BluetallyEndpointConfig(name="statuses", path="/statuses"),
    "depreciations": BluetallyEndpointConfig(name="depreciations", path="/depreciations"),
    "maintenances": BluetallyEndpointConfig(name="maintenances", path="/maintenances"),
    "audits": BluetallyEndpointConfig(name="audits", path="/audits"),
}

ENDPOINTS = tuple(BLUETALLY_ENDPOINTS.keys())
