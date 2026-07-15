from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField

HEROKU_BASE_URL = "https://api.heroku.com"

# Heroku pages via the `Range` request header / `Next-Range` response header.
# Default page size is 200; the hard max is 1000.
DEFAULT_PAGE_SIZE = 1000

# Hard cap on pages walked per list (per app for fan-out endpoints) so a runaway
# cursor can't scan unbounded history. 1000-row pages make this 100k rows per list.
MAX_PAGES_PER_LIST = 100


@dataclass
class HerokuEndpointConfig:
    name: str
    path: str  # contains an {app_id} placeholder for fan-out endpoints
    fan_out_over_apps: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp used for datetime partitioning. All Heroku resources carry
    # `created_at`; never partition on `updated_at` (partitions would rewrite every sync).
    partition_key: str | None = "created_at"
    # Attribute used in the `Range` header for stable pagination. `id` is Heroku's default
    # sort attribute and is accepted on every list endpoint.
    range_attribute: str = "id"
    should_sync_default: bool = True


# Heroku's Platform API v3 exposes no updated-since/created-since query filters, so every
# endpoint syncs as a full refresh. The `Range` header can filter some endpoints server-side
# (e.g. /apps advertises ranges on `updated_at`), but that behavior is per-endpoint and
# unverified against the live API, so we don't build incremental sync on it yet.
HEROKU_ENDPOINTS: dict[str, HerokuEndpointConfig] = {
    "apps": HerokuEndpointConfig(
        name="apps",
        path="/apps",
    ),
    "addons": HerokuEndpointConfig(
        name="addons",
        path="/addons",
    ),
    "builds": HerokuEndpointConfig(
        name="builds",
        path="/apps/{app_id}/builds",
        fan_out_over_apps=True,
    ),
    "collaborators": HerokuEndpointConfig(
        name="collaborators",
        path="/apps/{app_id}/collaborators",
        fan_out_over_apps=True,
    ),
    "domains": HerokuEndpointConfig(
        name="domains",
        path="/apps/{app_id}/domains",
        fan_out_over_apps=True,
    ),
    # Dynos are a point-in-time snapshot of running processes; the list is small and churns
    # constantly, so partitioning adds nothing.
    "dynos": HerokuEndpointConfig(
        name="dynos",
        path="/apps/{app_id}/dynos",
        fan_out_over_apps=True,
        partition_key=None,
    ),
    "formation": HerokuEndpointConfig(
        name="formation",
        path="/apps/{app_id}/formation",
        fan_out_over_apps=True,
        partition_key=None,
    ),
    "invoices": HerokuEndpointConfig(
        name="invoices",
        path="/account/invoices",
    ),
    "pipelines": HerokuEndpointConfig(
        name="pipelines",
        path="/pipelines",
    ),
    "releases": HerokuEndpointConfig(
        name="releases",
        path="/apps/{app_id}/releases",
        fan_out_over_apps=True,
    ),
    "teams": HerokuEndpointConfig(
        name="teams",
        path="/teams",
    ),
}

ENDPOINTS = tuple(HEROKU_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in HEROKU_ENDPOINTS}
