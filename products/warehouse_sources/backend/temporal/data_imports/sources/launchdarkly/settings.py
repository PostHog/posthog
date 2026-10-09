from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.backend.types import IncrementalField


@dataclass(frozen=True)
class LaunchDarklyEndpointConfig:
    name: str
    # Path under the API root. A ``{project_key}`` placeholder marks a fan-out endpoint
    # that must be queried once per project.
    path: str
    primary_key: list[str]
    # Fan-out endpoints depend on the list of projects; we inject ``_project_key`` into
    # every row so a single table stays meaningful (and uniquely keyed) across projects.
    requires_project: bool = False
    # Environment-scoped endpoints take both ``{project_key}`` and ``{environment_key}`` and are
    # queried once per environment of every project, with ``_project_key`` and ``_environment_key``
    # injected into every row.
    requires_environment: bool = False
    # LaunchDarkly's list endpoints default to a small page size; 20 is the documented
    # safe default across every endpoint we sync. Raise per-endpoint only once verified.
    # ``None`` for endpoints that return every row in one response and take no ``limit``.
    page_size: int | None = 20
    extra_params: dict[str, Any] = field(default_factory=dict)
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
    "segments": LaunchDarklyEndpointConfig(
        name="segments",
        path="/segments/{project_key}/{environment_key}",
        primary_key=["key", "_project_key", "_environment_key"],
        requires_environment=True,
        extra_params={"sort": "creationDate"},
    ),
    "flag_statuses": LaunchDarklyEndpointConfig(
        name="flag_statuses",
        path="/flag-statuses/{project_key}/{environment_key}",
        # Status rows carry no flag key field; ``_flag_key`` is derived from the row's self link.
        primary_key=["_flag_key", "_project_key", "_environment_key"],
        requires_environment=True,
        page_size=None,
    ),
    "experiments": LaunchDarklyEndpointConfig(
        name="experiments",
        path="/projects/{project_key}/environments/{environment_key}/experiments",
        primary_key=["key", "_project_key", "_environment_key"],
        requires_environment=True,
        extra_params={
            # The API returns only active experiments and only the current iteration by default.
            "lifecycleState": "active,archived",
            "expand": "previousIterations,draftIteration,secondaryMetrics,treatments,analysisConfig",
        },
    ),
    "holdouts": LaunchDarklyEndpointConfig(
        name="holdouts",
        path="/projects/{project_key}/environments/{environment_key}/holdouts",
        primary_key=["_id", "_project_key", "_environment_key"],
        requires_environment=True,
    ),
}

ENDPOINTS = tuple(LAUNCHDARKLY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LAUNCHDARKLY_ENDPOINTS.items()
}
