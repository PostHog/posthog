from dataclasses import dataclass, field


@dataclass
class StiggEndpointConfig:
    name: str
    path: str
    # Most Stigg object IDs (customer/subscription/feature slugs) are unique across the
    # environment the API key scopes to, so `id` is a safe default primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp used for datetime partitioning. `createdAt` is a required
    # field on every list DTO in Stigg's OpenAPI spec and never changes after creation.
    partition_key: str = "createdAt"


# Stigg REST API (https://api.stigg.io/api/v1) list endpoints. All are full refresh only:
# the list endpoints expose a server-side `createdAt` range filter but no updated-since
# filter, and billing objects (subscriptions, plans, customers) mutate in place — syncing
# incrementally on creation time would permanently miss those updates, so we do not
# advertise it. Change capture on Stigg's side is webhook/queue based, with manual setup
# only (no programmatic webhook management API).
STIGG_ENDPOINTS: dict[str, StiggEndpointConfig] = {
    "customers": StiggEndpointConfig(name="customers", path="/customers"),
    "subscriptions": StiggEndpointConfig(name="subscriptions", path="/subscriptions"),
    "products": StiggEndpointConfig(name="products", path="/products"),
    # Plans and addons are versioned packages: `id` is the package slug shared by every
    # version, so the composite key with `versionNumber` keeps rows unique table-wide.
    "plans": StiggEndpointConfig(
        name="plans",
        path="/plans",
        primary_keys=["id", "versionNumber"],
    ),
    "addons": StiggEndpointConfig(
        name="addons",
        path="/addons",
        primary_keys=["id", "versionNumber"],
    ),
    "features": StiggEndpointConfig(name="features", path="/features"),
    "coupons": StiggEndpointConfig(name="coupons", path="/coupons"),
}

ENDPOINTS = tuple(STIGG_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
