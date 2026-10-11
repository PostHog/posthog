from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


@frozen
class CircleCIEndpointConfig:
    name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field used for datetime partitioning. Jobs don't expose their own
    # creation timestamp, so they partition on the parent workflow's created_at injected by
    # the transport.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# CircleCI API v2 list endpoints (pipelines/workflows/jobs) expose no server-side timestamp
# filter — they always return newest-first with token pagination — so every stream is full
# refresh with hard page caps. Only the insights endpoints take start/end date params (with a
# 90-day lookback), and those are a deliberate follow-up.
CIRCLECI_ENDPOINTS: dict[str, CircleCIEndpointConfig] = {
    "pipelines": CircleCIEndpointConfig(
        name="pipelines",
        partition_key="created_at",
    ),
    "workflows": CircleCIEndpointConfig(
        name="workflows",
        partition_key="created_at",
    ),
    "jobs": CircleCIEndpointConfig(
        name="jobs",
        partition_key="workflow_created_at",
    ),
    "projects": CircleCIEndpointConfig(
        name="projects",
    ),
    "components": CircleCIEndpointConfig(
        name="components",
        partition_key="created_at",
    ),
    "component_versions": CircleCIEndpointConfig(
        name="component_versions",
        # A version payload carries no id of its own, and the same version name can be live in
        # several environments and namespaces, so identity is the component plus the deploy
        # target. last_deployed_at moves on every redeploy, so there is no partition key.
        primary_keys=["component_id", "environment_id", "namespace", "name"],
    ),
    "users": CircleCIEndpointConfig(
        name="users",
    ),
}

ENDPOINTS = tuple(CIRCLECI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CIRCLECI_ENDPOINTS.items() if config.incremental_fields
}
