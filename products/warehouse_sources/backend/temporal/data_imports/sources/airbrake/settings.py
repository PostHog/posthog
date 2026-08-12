from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class AirbrakeEndpointConfig:
    name: str
    # Path template; `{project_id}` / `{group_id}` are resolved during fan-out.
    path: str
    # Key wrapping the item collection in the response body (e.g. {"count": 1, "groups": [...]}).
    collection_key: str
    # None for endpoints whose rows expose no unique identifier (deploys) — full refresh only.
    primary_keys: list[str] | None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: str | None = None
    should_sync_default: bool = True
    # Fan-out depth: 0 = top-level, 1 = per project, 2 = per project per group.
    fan_out_depth: int = 0


AIRBRAKE_ENDPOINTS: dict[str, AirbrakeEndpointConfig] = {
    "projects": AirbrakeEndpointConfig(
        name="projects",
        path="/api/v4/projects",
        collection_key="projects",
        primary_keys=["id"],
    ),
    "groups": AirbrakeEndpointConfig(
        name="groups",
        path="/api/v4/projects/{project_id}/groups",
        collection_key="groups",
        # Group ids are unique across projects (the cross-project /api/v4/groups endpoint
        # addresses groups by bare id).
        primary_keys=["id"],
        partition_key="createdAt",
        fan_out_depth=1,
        incremental_fields=[
            {
                "label": "createdAt",
                "type": IncrementalFieldType.DateTime,
                "field": "createdAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "deploys": AirbrakeEndpointConfig(
        name="deploys",
        path="/api/v4/projects/{project_id}/deploys",
        collection_key="deploys",
        # Deploy rows carry no id or timestamp, so there is nothing to merge or partition on.
        primary_keys=None,
        fan_out_depth=1,
    ),
    # One paginated request per error group across every project, so this is the most
    # API-expensive table — opt-in rather than synced by default.
    "notices": AirbrakeEndpointConfig(
        name="notices",
        path="/api/v4/projects/{project_id}/groups/{group_id}/notices",
        collection_key="notices",
        primary_keys=["groupId", "id"],
        partition_key="createdAt",
        should_sync_default=False,
        fan_out_depth=2,
    ),
}

ENDPOINTS = tuple(AIRBRAKE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AIRBRAKE_ENDPOINTS.items()
}
