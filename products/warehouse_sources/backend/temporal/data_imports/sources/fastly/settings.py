from dataclasses import dataclass, field
from typing import Literal

# How each Fastly endpoint is fetched:
# - "object":           GET returns a single object (e.g. /current_user).
# - "service_list":     GET /service returns a page-paginated array (Link header for next page).
# - "version_list":     fan out over every service, list that service's versions.
# - "version_resource": fan out over every service, fetch a resource scoped to the service's
#                       currently-active version (domains, backends, ACLs, dictionaries).
FastlyEndpointKind = Literal["object", "service_list", "version_list", "version_resource"]


@dataclass
class FastlyEndpointConfig:
    name: str
    path: str
    kind: FastlyEndpointKind
    # Partition on a STABLE creation timestamp so partitions aren't rewritten every sync.
    partition_key: str | None = "created_at"
    should_sync_default: bool = True
    description: str | None = None
    # Unique across the whole table. Fan-out children aggregate rows from every parent, so the
    # key includes the parent (service) identifier unless the resource id is globally unique.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Version-scoped resource paths carry `{service_id}` and `{version}` placeholders that the
# transport formats with the service id and its active version number.
FASTLY_ENDPOINTS: dict[str, FastlyEndpointConfig] = {
    "current_user": FastlyEndpointConfig(
        name="current_user",
        path="/current_user",
        kind="object",
        primary_keys=["id"],
        description="The user whose API token authenticates this connection.",
    ),
    "services": FastlyEndpointConfig(
        name="services",
        path="/service",
        kind="service_list",
        primary_keys=["id"],
        description="Every Fastly service in the account.",
    ),
    "service_versions": FastlyEndpointConfig(
        name="service_versions",
        path="/service/{service_id}/version",
        kind="version_list",
        primary_keys=["service_id", "number"],
        description="All configuration versions for each service.",
    ),
    "service_domains": FastlyEndpointConfig(
        name="service_domains",
        path="/service/{service_id}/version/{version}/domain",
        kind="version_resource",
        primary_keys=["service_id", "version", "name"],
        description="Domains attached to each service's active version.",
    ),
    "service_backends": FastlyEndpointConfig(
        name="service_backends",
        path="/service/{service_id}/version/{version}/backend",
        kind="version_resource",
        primary_keys=["service_id", "version", "name"],
        description="Origin backends configured on each service's active version.",
    ),
    "service_acls": FastlyEndpointConfig(
        name="service_acls",
        path="/service/{service_id}/version/{version}/acl",
        kind="version_resource",
        # ACL ids are globally unique; the service id is kept in the key defensively.
        primary_keys=["service_id", "id"],
        description="Access control lists on each service's active version.",
    ),
    "service_dictionaries": FastlyEndpointConfig(
        name="service_dictionaries",
        path="/service/{service_id}/version/{version}/dictionary",
        kind="version_resource",
        # Dictionary ids are globally unique; the service id is kept in the key defensively.
        primary_keys=["service_id", "id"],
        description="Edge dictionaries on each service's active version.",
    ),
}

ENDPOINTS = tuple(FASTLY_ENDPOINTS.keys())
