from collections.abc import Callable
from dataclasses import field
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class NorthflankEndpointConfig:
    name: str
    # Path relative to the API base. Fan-out children use a `{project_id}` placeholder.
    path: str
    # Key inside the response `data` object that holds the row array (e.g. `data.projects`).
    data_key: str
    # Whether the endpoint is queried once per project (fan-out) rather than once globally.
    fan_out_over_projects: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field for datetime partitioning. Inventory objects other than volumes
    # expose no timestamps, so they ship unpartitioned.
    partition_key: Optional[str] = None
    # Project-scoped endpoint to fan out over a second time (e.g. a job's runs). The path then also
    # carries a `{parent_id}` placeholder, filled from each parent row's `id`.
    parent: Optional[str] = None
    # Column the parent id is injected under on child rows.
    parent_id_key: Optional[str] = None
    # Skips parents the child endpoint does not apply to.
    include_parent: Optional[Callable[[dict[str, Any]], bool]] = None
    paginated: bool = True
    page_size_param: str = "per_page"
    params: dict[str, Any] = field(default_factory=dict)
    # Query param that takes the incremental watermark as a Unix timestamp. Full refresh sends 0.
    incremental_param: Optional[str] = None


def _service_has_builds(service: dict[str, Any]) -> bool:
    # Deployment services run an image built elsewhere, so they have no builds of their own.
    return service.get("serviceType") != "deployment"


# Only the billing usage endpoint documents a server-side timestamp filter (`startTime`); every other
# stream is full refresh. Most resources are project-scoped, so the fan-out streams first list
# projects then query the child endpoint once per project.
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
    "service_builds": NorthflankEndpointConfig(
        name="service_builds",
        path="/v1/projects/{project_id}/services/{parent_id}/build",
        data_key="builds",
        fan_out_over_projects=True,
        parent="services",
        parent_id_key="serviceId",
        include_parent=_service_has_builds,
        primary_keys=["projectId", "serviceId", "id"],
        partition_key="createdAt",
    ),
    "job_runs": NorthflankEndpointConfig(
        name="job_runs",
        path="/v1/projects/{project_id}/jobs/{parent_id}/runs",
        data_key="runs",
        fan_out_over_projects=True,
        parent="jobs",
        parent_id_key="jobId",
        primary_keys=["projectId", "jobId", "id"],
        partition_key="startedAt",
    ),
    "plans": NorthflankEndpointConfig(
        name="plans",
        path="/v1/plans",
        data_key="plans",
        # A small static catalog that documents no pagination params.
        paginated=False,
    ),
    "usage": NorthflankEndpointConfig(
        name="usage",
        path="/v1/billing/usage",
        data_key="usage",
        # The default hourly granularity returns one entry per billing hour.
        primary_keys=["timestamp"],
        page_size_param="perPage",
        # Accounts still on the legacy billing contract otherwise get a different row shape.
        params={"removeLegacyFields": "true"},
        incremental_param="startTime",
    ),
}

ENDPOINTS = tuple(NORTHFLANK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "usage": [
        {
            "label": "timestamp",
            "type": IncrementalFieldType.DateTime,
            "field": "timestamp",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
}
