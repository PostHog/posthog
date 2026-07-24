from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class HoneybadgerEndpointConfig:
    name: str
    # Path template under the v2 base URL; `{project_id}` / `{fault_id}` are filled in by the fan-out.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Incremental field name -> query param that server-side filters on it (Unix timestamp).
    incremental_params: dict[str, str] = field(default_factory=dict)
    default_incremental_field: str | None = None
    partition_key: str | None = None  # Stable creation-time field; never a mutating timestamp
    fan_out_over_faults: bool = False  # Two-level fan-out: projects -> faults -> {endpoint}
    should_sync_default: bool = True


_created_at_field: IncrementalField = {
    "label": "created_at",
    "type": IncrementalFieldType.DateTime,
    "field": "created_at",
    "field_type": IncrementalFieldType.DateTime,
}

HONEYBADGER_ENDPOINTS: dict[str, HoneybadgerEndpointConfig] = {
    "projects": HoneybadgerEndpointConfig(
        name="projects",
        path="/projects",
        # The projects list has no server-side timestamp filter, so it's full refresh only.
        incremental_fields=[],
    ),
    "faults": HoneybadgerEndpointConfig(
        name="faults",
        path="/projects/{project_id}/faults",
        # Fault ids look globally unique, but the API doesn't document that — include the
        # parent project id so the key is unique table-wide across the fan-out.
        primary_keys=["project_id", "id"],
        incremental_fields=[
            _created_at_field,
            {
                "label": "last_notice_at",
                "type": IncrementalFieldType.DateTime,
                "field": "last_notice_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        # `created_after` only picks up new faults; `occurred_after` (filters on the fault's
        # last notice) also re-pulls existing faults that reoccurred, keeping counts fresh.
        incremental_params={"created_at": "created_after", "last_notice_at": "occurred_after"},
        default_incremental_field="last_notice_at",
        partition_key="created_at",
    ),
    "notices": HoneybadgerEndpointConfig(
        name="notices",
        path="/projects/{project_id}/faults/{fault_id}/notices",
        # Notice ids are UUIDs.
        primary_keys=["id"],
        incremental_fields=[_created_at_field],
        incremental_params={"created_at": "created_after"},
        default_incremental_field="created_at",
        partition_key="created_at",
        fan_out_over_faults=True,
        # One request per fault minimum against a 360 req/hour quota — opt-in only.
        should_sync_default=False,
    ),
    "deploys": HoneybadgerEndpointConfig(
        name="deploys",
        path="/projects/{project_id}/deploys",
        primary_keys=["project_id", "id"],
        incremental_fields=[_created_at_field],
        incremental_params={"created_at": "created_after"},
        default_incremental_field="created_at",
        partition_key="created_at",
    ),
    "sites": HoneybadgerEndpointConfig(
        name="sites",
        path="/projects/{project_id}/sites",
        # Site ids are UUIDs; keep the parent project id in the key anyway for consistency.
        primary_keys=["project_id", "id"],
        # The sites (uptime checks) list has no server-side timestamp filter.
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(HONEYBADGER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HONEYBADGER_ENDPOINTS.items()
}
