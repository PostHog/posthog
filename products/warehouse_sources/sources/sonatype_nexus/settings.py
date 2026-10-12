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
}

ENDPOINTS = tuple(SONATYPE_NEXUS_ENDPOINTS.keys())
