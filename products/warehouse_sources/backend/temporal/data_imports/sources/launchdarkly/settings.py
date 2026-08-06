from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class LaunchDarklyEndpointConfig:
    name: str
    # Path under the API root. A ``{project_key}`` placeholder marks a fan-out endpoint
    # that must be queried once per project.
    path: str
    primary_key: list[str]
    # Fan-out endpoints depend on the list of projects; we inject ``_project_key`` into
    # every row so a single table stays meaningful (and uniquely keyed) across projects.
    requires_project: bool = False
    # LaunchDarkly's list endpoints default to a small page size; 20 is the documented
    # safe default across every endpoint we sync. Raise per-endpoint only once verified.
    page_size: int = 20
    # LaunchDarkly exposes no server-side timestamp filter on these resources (its
    # timestamps are epoch-millisecond integers and the public API offers no
    # ``updated_after``/``since`` parameter), so every endpoint is full-refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


LAUNCHDARKLY_ENDPOINTS: dict[str, LaunchDarklyEndpointConfig] = {
    "projects": LaunchDarklyEndpointConfig(
        name="projects",
        path="/projects",
        primary_key=["_id"],
    ),
    "members": LaunchDarklyEndpointConfig(
        name="members",
        path="/members",
        primary_key=["_id"],
    ),
    "auditlog": LaunchDarklyEndpointConfig(
        name="auditlog",
        path="/auditlog",
        primary_key=["_id"],
    ),
    "environments": LaunchDarklyEndpointConfig(
        name="environments",
        path="/projects/{project_key}/environments",
        primary_key=["_id"],
        requires_project=True,
    ),
    "metrics": LaunchDarklyEndpointConfig(
        name="metrics",
        path="/metrics/{project_key}",
        primary_key=["_id"],
        requires_project=True,
    ),
    "flags": LaunchDarklyEndpointConfig(
        name="flags",
        path="/flags/{project_key}",
        # Flag keys are unique only within a project, so the composite key includes the
        # injected ``_project_key``.
        primary_key=["key", "_project_key"],
        requires_project=True,
    ),
}

ENDPOINTS = tuple(LAUNCHDARKLY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LAUNCHDARKLY_ENDPOINTS.items()
}
