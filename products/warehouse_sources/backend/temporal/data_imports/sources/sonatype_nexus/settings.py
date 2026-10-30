from dataclasses import dataclass, field

# Nexus Repository's REST API is served per-instance under this base path.
NEXUS_API_PATH = "/service/rest/v1"


@dataclass
class SonatypeNexusEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Components and assets must be queried one repository at a time
    # (?repository=<name>), so these endpoints fan out over /repositories.
    per_repository: bool = False
    # Whether the endpoint returns the {items, continuationToken} envelope.
    # /repositories returns a plain JSON array with no pagination.
    paginated: bool = True


# The REST API exposes no server-side timestamp filter, so every table is full
# refresh only. No datetime partitioning either: repositories, tasks, and
# components carry no timestamp at all, and assets' `blobCreated` can be null
# for blobs created before the instance was upgraded to a version that records it.
SONATYPE_NEXUS_ENDPOINTS: dict[str, SonatypeNexusEndpointConfig] = {
    "repositories": SonatypeNexusEndpointConfig(
        name="repositories",
        path="/repositories",
        primary_keys=["name"],
        paginated=False,
    ),
    # Component/asset ids are opaque identifiers; uniqueness across repositories
    # isn't documented, so the repository is part of the key.
    "components": SonatypeNexusEndpointConfig(
        name="components",
        path="/components",
        primary_keys=["repository", "id"],
        per_repository=True,
    ),
    "assets": SonatypeNexusEndpointConfig(
        name="assets",
        path="/assets",
        primary_keys=["repository", "id"],
        per_repository=True,
    ),
    "tasks": SonatypeNexusEndpointConfig(
        name="tasks",
        path="/tasks",
    ),
    # A user id is only unique within its user source (realm), e.g. `default` vs `LDAP`.
    "users": SonatypeNexusEndpointConfig(
        name="users",
        path="/security/users",
        primary_keys=["source", "userId"],
        paginated=False,
    ),
    "roles": SonatypeNexusEndpointConfig(
        name="roles",
        path="/security/roles",
        primary_keys=["source", "id"],
        paginated=False,
    ),
    "privileges": SonatypeNexusEndpointConfig(
        name="privileges",
        path="/security/privileges",
        primary_keys=["name"],
        paginated=False,
    ),
    "blob_stores": SonatypeNexusEndpointConfig(
        name="blob_stores",
        path="/blobstores",
        primary_keys=["name"],
        paginated=False,
    ),
}

# Nexus caps a user search that names no source, or an external source, at 100 users.
# Only the local `default` source is listed in full.
NEXUS_DEFAULT_USER_SOURCE = "default"
NEXUS_USER_SEARCH_LIMIT = 100

ENDPOINTS = tuple(SONATYPE_NEXUS_ENDPOINTS.keys())
