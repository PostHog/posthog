from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Raygun's data API is a single global host (no regional variants) exposing v3 REST/JSON.
RAYGUN_BASE_URL = "https://api.raygun.com/v3"

# Page size for offset/count pagination. The API caps `count` at 500; 100 keeps individual
# responses small while limiting the number of round trips.
PAGE_SIZE = 100


@dataclass
class RaygunEndpointConfig:
    name: str
    # Path relative to RAYGUN_BASE_URL. Fan-out children carry a `{application_identifier}`
    # placeholder resolved once per application.
    path: str
    primary_keys: list[str]
    # `orderby` value passed on every request. Offset pagination over data that is being
    # inserted concurrently can skip or duplicate rows, so we always sort by a stable
    # (immutable or create-time) field to keep page boundaries deterministic.
    orderby: str
    # Stable create-time field used for datetime partitioning. Only set when the field is
    # guaranteed present on every row (in the API's `required` set) — never `lastSeenAt`/
    # `updatedAt`, which move over time and would rewrite partitions each sync.
    partition_key: Optional[str] = None
    # When True, iterate every application and call `path` per application. When False the
    # endpoint is a single top-level list.
    fan_out_over_applications: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Raygun exposes no server-side "updated since" filter on any list endpoint (only offset/count
# pagination plus an `orderby`), so every endpoint syncs as a full refresh — declaring an
# incremental field here would fetch every page anyway, giving no cost saving. See the source
# docstring and PR notes.
RAYGUN_ENDPOINTS: dict[str, RaygunEndpointConfig] = {
    "applications": RaygunEndpointConfig(
        name="applications",
        path="/applications",
        primary_keys=["identifier"],
        orderby="name",
    ),
    "error_groups": RaygunEndpointConfig(
        name="error_groups",
        path="/applications/{application_identifier}/error-groups",
        primary_keys=["applicationIdentifier", "identifier"],
        orderby="createdAt",
        partition_key="createdAt",
        fan_out_over_applications=True,
    ),
    "deployments": RaygunEndpointConfig(
        name="deployments",
        path="/applications/{application_identifier}/deployments",
        primary_keys=["applicationIdentifier", "identifier"],
        orderby="deployedAt",
        fan_out_over_applications=True,
    ),
    "customers": RaygunEndpointConfig(
        name="customers",
        path="/applications/{application_identifier}/customers",
        primary_keys=["applicationIdentifier", "identifier"],
        orderby="firstSeenAt",
        fan_out_over_applications=True,
    ),
    "sessions": RaygunEndpointConfig(
        name="sessions",
        path="/applications/{application_identifier}/sessions",
        primary_keys=["applicationIdentifier", "identifier"],
        orderby="startedAt",
        partition_key="startedAt",
        fan_out_over_applications=True,
    ),
    "pages": RaygunEndpointConfig(
        name="pages",
        path="/applications/{application_identifier}/pages",
        primary_keys=["applicationIdentifier", "identifier"],
        orderby="uri",
        fan_out_over_applications=True,
    ),
}

ENDPOINTS = tuple(RAYGUN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RAYGUN_ENDPOINTS.items()
}
