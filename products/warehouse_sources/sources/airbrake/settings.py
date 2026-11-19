from dataclasses import dataclass, field

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class AirbrakeStatsConfig:
    # Bucket size as each stats endpoint documents it: the project endpoint lists Go-style
    # durations ("24h"), the group endpoint lists names ("hour").
    period: str
    period_seconds: int
    # How far back a full refresh reads. An incremental run never reads further back either,
    # so a paused schema skips the buckets that fall out of this window.
    lookback_seconds: int


@dataclass(frozen=False)
class AirbrakeEndpointConfig:
    name: str
    # Path template; `{project_id}` / `{group_id}` are resolved during fan-out.
    path: str
    # Key wrapping the item collection in the response body (e.g. {"count": 1, "groups": [...]}).
    # Stats endpoints return parallel arrays, and this key names the array that gives one row per entry.
    collection_key: str
    # None for endpoints whose rows expose no unique identifier (deploys) — full refresh only.
    primary_keys: list[str] | None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: str | None = None
    should_sync_default: bool = True
    # Fan-out depth: 0 = top-level, 1 = per project, 2 = per project per group.
    fan_out_depth: int = 0
    stats: AirbrakeStatsConfig | None = None


_TIME_INCREMENTAL_FIELD: IncrementalField = {
    "label": "time",
    "type": IncrementalFieldType.DateTime,
    "field": "time",
    "field_type": IncrementalFieldType.DateTime,
}


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
    "activities": AirbrakeEndpointConfig(
        name="activities",
        path="/api/v4/projects/{project_id}/activities",
        collection_key="activities",
        # Activity rows carry no id, so there is nothing to merge on.
        primary_keys=None,
        fan_out_depth=1,
    ),
    "project_stats": AirbrakeEndpointConfig(
        name="project_stats",
        path="/api/v4/projects/{project_id}/stats",
        collection_key="time",
        primary_keys=["projectId", "time"],
        partition_key="time",
        fan_out_depth=1,
        incremental_fields=[_TIME_INCREMENTAL_FIELD],
        stats=AirbrakeStatsConfig(period="24h", period_seconds=24 * 60 * 60, lookback_seconds=90 * 24 * 60 * 60),
    ),
    # One request series per error group across every project, like notices, so it is opt-in.
    "group_stats": AirbrakeEndpointConfig(
        name="group_stats",
        path="/api/v4/projects/{project_id}/groups/{group_id}/stats",
        collection_key="time",
        primary_keys=["groupId", "time"],
        partition_key="time",
        should_sync_default=False,
        fan_out_depth=2,
        incremental_fields=[_TIME_INCREMENTAL_FIELD],
        stats=AirbrakeStatsConfig(period="hour", period_seconds=60 * 60, lookback_seconds=7 * 24 * 60 * 60),
    ),
}

ENDPOINTS = tuple(AIRBRAKE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AIRBRAKE_ENDPOINTS.items()
}
