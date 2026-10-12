from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class NorthflankEndpointConfig:
    name: str
    # Path relative to the API base. Fan-out children use a `{project_id}` placeholder.
    path: str
    # Key inside the response `data` object that holds the row array (e.g. `data.projects`).
    data_key: str
    # Whether the endpoint is queried once per project (fan-out) rather than once globally.
    fan_out_over_projects: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field for datetime partitioning. Only volumes document one; the other
    # list objects expose no timestamps, so they ship unpartitioned.
    partition_key: Optional[str] = None


# Northflank list endpoints document no server-side timestamp filter (no updated-since/created-after
# param), so every stream is full refresh. Most resources are project-scoped, so the fan-out streams
# first list projects then query the child endpoint once per project.
NORTHFLANK_ENDPOINTS: dict[str, NorthflankEndpointConfig] = {
    "projects": NorthflankEndpointConfig(
        name="projects",
        path="/v1/projects",
        data_key="projects",
    ),
    "services": NorthflankEndpointConfig(
        name="services",
        path="/v1/projects/{project_id}/services",
        data_key="services",
        fan_out_over_projects=True,
        # Service `id` is unique within a project, not across projects, so key on the pair.
        primary_keys=["projectId", "id"],
    ),
    "jobs": NorthflankEndpointConfig(
        name="jobs",
        path="/v1/projects/{project_id}/jobs",
        data_key="jobs",
        fan_out_over_projects=True,
        primary_keys=["projectId", "id"],
    ),
    "addons": NorthflankEndpointConfig(
        name="addons",
        path="/v1/projects/{project_id}/addons",
        data_key="addons",
        fan_out_over_projects=True,
        primary_keys=["projectId", "id"],
    ),
    "volumes": NorthflankEndpointConfig(
        name="volumes",
        path="/v1/projects/{project_id}/volumes",
        data_key="volumes",
        fan_out_over_projects=True,
        primary_keys=["projectId", "id"],
        partition_key="createdAt",
    ),
}

ENDPOINTS = tuple(NORTHFLANK_ENDPOINTS.keys())

# No endpoint exposes a server-side timestamp filter, so there are no advertised incremental fields.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
