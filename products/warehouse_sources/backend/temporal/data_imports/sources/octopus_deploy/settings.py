from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class OctopusDeployEndpointConfig:
    name: str
    # For space-scoped endpoints, relative to `/api/{space_id}`; for instance-level endpoints,
    # the full path under the host (e.g. `/api/spaces`).
    path: str
    # Almost every Octopus resource lives under `/api/Spaces-{n}/...`; the source fans out over
    # every space the API key can see and stamps `SpaceId` onto each row.
    space_scoped: bool = True
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Query param carrying the server-side date filter (`fromCompletedDate` on tasks, `from` on
    # events). Endpoints without one are full-refresh only.
    incremental_param: Optional[str] = None
    # Stable, immutable field to partition by. Never a last-modified style field (it mutates).
    partition_key: Optional[str] = None
    page_size: int = 100


OCTOPUS_DEPLOY_ENDPOINTS: dict[str, OctopusDeployEndpointConfig] = {
    "spaces": OctopusDeployEndpointConfig(
        name="spaces",
        path="/api/spaces",
        space_scoped=False,
    ),
    "projects": OctopusDeployEndpointConfig(
        name="projects",
        path="/projects",
    ),
    "project_groups": OctopusDeployEndpointConfig(
        name="project_groups",
        path="/projectgroups",
    ),
    "environments": OctopusDeployEndpointConfig(
        name="environments",
        path="/environments",
    ),
    "channels": OctopusDeployEndpointConfig(
        name="channels",
        path="/channels",
    ),
    "tenants": OctopusDeployEndpointConfig(
        name="tenants",
        path="/tenants",
    ),
    "machines": OctopusDeployEndpointConfig(
        name="machines",
        path="/machines",
    ),
    # Releases and deployments expose no server-side date filter (only project/environment
    # filters), so they are full-refresh only. Their creation timestamps are immutable and make
    # stable partition keys.
    "releases": OctopusDeployEndpointConfig(
        name="releases",
        path="/releases",
        partition_key="Assembled",
    ),
    "deployments": OctopusDeployEndpointConfig(
        name="deployments",
        path="/deployments",
        partition_key="Created",
    ),
    # Tasks accept `fromCompletedDate`, a genuine server-side filter on CompletedTime (verified:
    # a future cutoff returns zero rows). QueueTime is set once at creation and never mutates,
    # unlike CompletedTime which flips from null when the task finishes.
    "tasks": OctopusDeployEndpointConfig(
        name="tasks",
        path="/tasks",
        incremental_fields=[_datetime_incremental_field("CompletedTime")],
        incremental_param="fromCompletedDate",
        partition_key="QueueTime",
    ),
    # Audit events accept `from`, a server-side filter on Occurred. Events are immutable.
    "events": OctopusDeployEndpointConfig(
        name="events",
        path="/events",
        incremental_fields=[_datetime_incremental_field("Occurred")],
        incremental_param="from",
        partition_key="Occurred",
        page_size=200,
    ),
}

ENDPOINTS = tuple(OCTOPUS_DEPLOY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OCTOPUS_DEPLOY_ENDPOINTS.items()
}
