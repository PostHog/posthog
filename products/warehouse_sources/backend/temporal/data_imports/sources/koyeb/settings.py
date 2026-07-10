from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class KoyebEndpointConfig:
    name: str
    # API path, e.g. "/v1/apps".
    path: str
    # Envelope key the list of rows lives under, e.g. {"apps": [...], "has_next": ...}.
    data_key: str
    # Primary key columns for dedup on merge. Composite where a single field is not unique table-wide.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field to partition by. Never a mutable field (updated_at) — partitions
    # would rewrite on every sync.
    partition_key: Optional[str] = None
    # Advertised incremental cursor options for the schema picker. Empty => full refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # True only when the API exposes a genuine server-side timestamp filter for this endpoint
    # (Koyeb documents starting_time/ending_time on /v1/instances and /v1/usages/details). Every
    # other endpoint offers no updated-since filter, so it is full refresh regardless of any
    # created_at column it happens to carry.
    supports_incremental: bool = False
    # Query param that carries the incremental lower bound (Koyeb: "starting_time").
    time_window_param: Optional[str] = None
    # Whether the table is selected for sync by default in the schema picker.
    should_sync_default: bool = True


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


KOYEB_ENDPOINTS: dict[str, KoyebEndpointConfig] = {
    # --- Config entities: created_at/updated_at exist but there is no updated-since list filter,
    # so full refresh. They are small (an org's apps/services/deployments), so re-reading is cheap.
    "apps": KoyebEndpointConfig(
        name="apps",
        path="/v1/apps",
        data_key="apps",
        partition_key="created_at",
    ),
    "services": KoyebEndpointConfig(
        name="services",
        path="/v1/services",
        data_key="services",
        partition_key="created_at",
    ),
    "deployments": KoyebEndpointConfig(
        name="deployments",
        path="/v1/deployments",
        data_key="deployments",
        partition_key="created_at",
    ),
    "regional_deployments": KoyebEndpointConfig(
        name="regional_deployments",
        path="/v1/regional_deployments",
        data_key="regional_deployments",
        partition_key="created_at",
    ),
    "domains": KoyebEndpointConfig(
        name="domains",
        path="/v1/domains",
        data_key="domains",
        partition_key="created_at",
    ),
    "secrets": KoyebEndpointConfig(
        name="secrets",
        path="/v1/secrets",
        data_key="secrets",
        partition_key="created_at",
    ),
    "volumes": KoyebEndpointConfig(
        name="volumes",
        path="/v1/volumes",
        data_key="volumes",
        partition_key="created_at",
    ),
    "snapshots": KoyebEndpointConfig(
        name="snapshots",
        path="/v1/snapshots",
        data_key="snapshots",
        partition_key="created_at",
    ),
    "instance_snapshots": KoyebEndpointConfig(
        name="instance_snapshots",
        path="/v1/instance_snapshots",
        data_key="instance_snapshots",
        partition_key="created_at",
    ),
    "organization_members": KoyebEndpointConfig(
        name="organization_members",
        path="/v1/organization_members",
        data_key="members",
        # No created_at; joined_at is the stable creation-time field.
        partition_key="joined_at",
    ),
    # --- Append-only event/activity streams: immutable rows with a unique id, but the API exposes
    # only order + offset, no server-side time filter. Merge on id keeps the tables idempotent; we
    # do not claim incremental because every run would still page from offset 0 (identical API cost
    # to a full refresh), which the skill explicitly rules out as "not incremental".
    "app_events": KoyebEndpointConfig(
        name="app_events",
        path="/v1/app_events",
        data_key="events",
        partition_key="when",
    ),
    "service_events": KoyebEndpointConfig(
        name="service_events",
        path="/v1/service_events",
        data_key="events",
        partition_key="when",
    ),
    "deployment_events": KoyebEndpointConfig(
        name="deployment_events",
        path="/v1/deployment_events",
        data_key="events",
        partition_key="when",
    ),
    "instance_events": KoyebEndpointConfig(
        name="instance_events",
        path="/v1/instance_events",
        data_key="events",
        partition_key="when",
    ),
    "activities": KoyebEndpointConfig(
        name="activities",
        path="/v1/activities",
        data_key="activities",
        partition_key="created_at",
    ),
    # --- Incremental endpoints: Koyeb documents starting_time/ending_time date-time windows here
    # (and only here), so these get a genuine server-side lower bound driven by the stored watermark.
    "instances": KoyebEndpointConfig(
        name="instances",
        path="/v1/instances",
        data_key="instances",
        partition_key="created_at",
        supports_incremental=True,
        time_window_param="starting_time",
        incremental_fields=[_datetime_field("created_at")],
    ),
    # Usage/billing records windowed by time. No single unique id, so the primary key is the
    # composite (deployment_id, instance_id, started_at): one usage window per instance-in-deployment
    # per start time. started_at is the incremental cursor and the stable partition key.
    "usage_details": KoyebEndpointConfig(
        name="usage_details",
        path="/v1/usages/details",
        data_key="usage_details",
        primary_keys=["deployment_id", "instance_id", "started_at"],
        partition_key="started_at",
        supports_incremental=True,
        time_window_param="starting_time",
        incremental_fields=[_datetime_field("started_at")],
    ),
}

ENDPOINTS = tuple(KOYEB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KOYEB_ENDPOINTS.items()
}
