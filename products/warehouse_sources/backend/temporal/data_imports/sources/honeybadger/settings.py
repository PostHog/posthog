from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class HoneybadgerEndpointConfig:
    name: str
    # Path template under the v2 base URL; `{project_id}` / `{fault_id}` / `{site_id}` are filled in by the fan-out.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Incremental field name -> query param that server-side filters on it (Unix timestamp).
    incremental_params: dict[str, str] = field(default_factory=dict)
    default_incremental_field: str | None = None
    # Incremental field name -> query param on the fan-out parent list that the watermark also bounds.
    parent_incremental_params: dict[str, str] = field(default_factory=dict)
    # Fan-out parent field -> column injected into each child row.
    parent_fields: dict[str, str] = field(default_factory=dict)
    partition_key: str | None = None  # Stable creation-time field; never a mutating timestamp
    fan_out_parent: Literal["faults", "sites"] | None = None  # Two-level fan-out: projects -> {parent} -> {endpoint}
    # False for endpoints that return a bare JSON array with no `limit` / `links.next` paging.
    paginated: bool = True
    # Response is `[epoch_seconds, count]` pairs instead of objects.
    time_series: bool = False
    query_params: dict[str, str] = field(default_factory=dict)
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
        parent_incremental_params={"created_at": "occurred_after"},
        partition_key="created_at",
        fan_out_parent="faults",
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
    "environments": HoneybadgerEndpointConfig(
        name="environments",
        path="/projects/{project_id}/environments",
        primary_keys=["project_id", "id"],
        incremental_fields=[],
        partition_key="created_at",
    ),
    "occurrences": HoneybadgerEndpointConfig(
        name="occurrences",
        path="/projects/{project_id}/occurrences",
        primary_keys=["project_id", "bucket_start"],
        # The API only serves a rolling window of buckets with no time filter; `month` returns
        # the most recent month in one-day buckets.
        incremental_fields=[],
        partition_key="bucket_start",
        paginated=False,
        time_series=True,
        query_params={"period": "month"},
    ),
    "affected_users": HoneybadgerEndpointConfig(
        name="affected_users",
        path="/projects/{project_id}/faults/{fault_id}/affected_users",
        primary_keys=["project_id", "fault_id", "user"],
        # The endpoint has no time filter, but a fault's affected users only change when it gets
        # a new notice, so the fault's last notice time bounds the fault enumeration instead.
        incremental_fields=[
            {
                "label": "fault_last_notice_at",
                "type": IncrementalFieldType.DateTime,
                "field": "fault_last_notice_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        default_incremental_field="fault_last_notice_at",
        parent_incremental_params={"fault_last_notice_at": "occurred_after"},
        parent_fields={"last_notice_at": "fault_last_notice_at"},
        fan_out_parent="faults",
        paginated=False,
        # One request per fault against a 360 req/hour quota — opt-in only.
        should_sync_default=False,
    ),
    "outages": HoneybadgerEndpointConfig(
        name="outages",
        path="/projects/{project_id}/sites/{site_id}/outages",
        # Outages have no id of their own.
        primary_keys=["project_id", "site_id", "created_at"],
        incremental_fields=[_created_at_field],
        incremental_params={"created_at": "created_after"},
        default_incremental_field="created_at",
        partition_key="created_at",
        fan_out_parent="sites",
    ),
}

ENDPOINTS = tuple(HONEYBADGER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HONEYBADGER_ENDPOINTS.items()
}
