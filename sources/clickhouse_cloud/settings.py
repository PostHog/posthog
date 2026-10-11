from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# usageCost windows span at most 31 days per request (from_date..to_date, both inclusive).
USAGE_COST_MAX_WINDOW_DAYS = 31

# Recent usage cost records are restated until ClickHouse locks them (the API marks them
# `locked=false`, "subject to change until locked"). The lock cadence is undocumented, so re-pull a
# full billing month on every incremental run; merge dedupes the overlap on the primary key and the
# extra window costs at most one additional request per sync.
USAGE_COST_LOOKBACK_SECONDS = 60 * 60 * 24 * 31


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


def _date_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.Date,
        "field": name,
        "field_type": IncrementalFieldType.Date,
    }


@dataclass
class ClickhouseCloudEndpointConfig:
    name: str
    # Path relative to the API host, with {organization_id} / {service_id} placeholders.
    path: str
    primary_keys: list[str]
    # Stable creation-style field used for datetime partitioning — never an updated-style field.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only True where the API exposes a genuine server-side time filter: usageCost's required
    # from_date/to_date window and activities' optional from_date. Every other endpoint returns a
    # complete unfiltered array, so those are full-refresh only.
    supports_incremental: bool = False
    # usage_cost records get restated until locked and activities' server-side filter is documented
    # but not verifiable without live credentials, so both incremental endpoints are merge-only —
    # append would materialize re-pulled rows as duplicates.
    supports_append: bool = False
    # backups has no org-wide list endpoint; it fans out one request per service.
    fan_out_over_services: bool = False
    should_sync_default: bool = True
    # Re-read window (seconds) the pipeline subtracts from the incremental watermark before it
    # reaches the source, so each run re-pulls recently-restated records.
    default_incremental_lookback_seconds: Optional[int] = None
    description: Optional[str] = None


CLICKHOUSE_CLOUD_ENDPOINTS: dict[str, ClickhouseCloudEndpointConfig] = {
    "organizations": ClickhouseCloudEndpointConfig(
        name="organizations",
        path="/v1/organizations",
        primary_keys=["id"],
        description="The organization the API key is scoped to (the API returns exactly one).",
    ),
    "services": ClickhouseCloudEndpointConfig(
        name="services",
        path="/v1/organizations/{organization_id}/services",
        primary_keys=["organizationId", "id"],
        description="All ClickHouse Cloud services in the organization, including state, tier, region, and scaling configuration.",
    ),
    "usage_cost": ClickhouseCloudEndpointConfig(
        name="usage_cost",
        path="/v1/organizations/{organization_id}/usageCost",
        primary_keys=["organizationId", "date", "entityId"],
        partition_key="date",
        supports_incremental=True,
        incremental_fields=[_date_incremental_field("date")],
        default_incremental_lookback_seconds=USAGE_COST_LOOKBACK_SECONDS,
        description="Daily per-entity usage cost records in ClickHouse Credits (CHCs), broken down by storage, compute, backup, and data transfer.",
    ),
    "api_keys": ClickhouseCloudEndpointConfig(
        name="api_keys",
        path="/v1/organizations/{organization_id}/keys",
        primary_keys=["organizationId", "id"],
        description="All API keys in the organization (metadata only — the API never returns key secrets).",
    ),
    "members": ClickhouseCloudEndpointConfig(
        name="members",
        path="/v1/organizations/{organization_id}/members",
        primary_keys=["organizationId", "userId"],
        description="All members of the organization and their roles.",
    ),
    "activities": ClickhouseCloudEndpointConfig(
        name="activities",
        path="/v1/organizations/{organization_id}/activities",
        primary_keys=["organizationId", "id"],
        partition_key="createdAt",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("createdAt")],
        description="The organization audit log: service, key, and member changes with actor details.",
    ),
    "backups": ClickhouseCloudEndpointConfig(
        name="backups",
        path="/v1/organizations/{organization_id}/services/{service_id}/backups",
        primary_keys=["organizationId", "serviceId", "id"],
        partition_key="startedAt",
        fan_out_over_services=True,
        description="Backups for every service in the organization (one API request per service).",
    ),
}

ENDPOINTS = tuple(CLICKHOUSE_CLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CLICKHOUSE_CLOUD_ENDPOINTS.items()
}
