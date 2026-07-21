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
class SentinelOneEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Field used to build the server-side `<field>__gte` filter when the user hasn't
    # picked one. Only set on endpoints whose list API documents the filter param.
    default_incremental_field: Optional[str] = None
    # Stable, immutable field to partition by. Never updatedAt (it mutates).
    partition_key: Optional[str] = None
    primary_key: str = "id"
    # SentinelOne caps `limit` at 1000 for most list endpoints; endpoints with a
    # smaller documented cap override this.
    page_size: int = 1000
    # Key under which the row list lives in the response `data` value. Most list
    # endpoints return `data` as a plain list; sites nests it (`data.sites`).
    data_key: Optional[str] = None
    # Nested object to hoist createdAt/updatedAt from when they're missing at the
    # top level (threats keep their timestamps under `threatInfo`).
    hoist_datetime_fields_from: Optional[str] = None


# The stream set mirrors what dedicated SentinelOne collectors (Sumo Logic, Elastic)
# warehouse: detections, fleet inventory, and the audit/event log, plus the small
# grouping dimensions (groups, sites) they join against.
SENTINELONE_ENDPOINTS: dict[str, SentinelOneEndpointConfig] = {
    "threats": SentinelOneEndpointConfig(
        name="threats",
        path="/threats",
        # Threats expose server-side createdAt__gte and updatedAt__gte filters.
        # updatedAt is the default cursor so mitigation-status changes are re-synced.
        incremental_fields=[
            _datetime_incremental_field("updatedAt"),
            _datetime_incremental_field("createdAt"),
        ],
        default_incremental_field="updatedAt",
        partition_key="createdAt",
        hoist_datetime_fields_from="threatInfo",
    ),
    "agents": SentinelOneEndpointConfig(
        name="agents",
        path="/agents",
        # Agents expose updatedAt__gte and createdAt__gte; updatedAt is the useful
        # cursor since endpoint health/inventory fields mutate constantly.
        incremental_fields=[
            _datetime_incremental_field("updatedAt"),
            _datetime_incremental_field("createdAt"),
        ],
        default_incremental_field="updatedAt",
        partition_key="createdAt",
    ),
    "activities": SentinelOneEndpointConfig(
        name="activities",
        path="/activities",
        # The activity log is append-only; createdAt__gte is the documented filter.
        incremental_fields=[_datetime_incremental_field("createdAt")],
        default_incremental_field="createdAt",
        partition_key="createdAt",
    ),
    # Groups and sites are small dimension tables. Their list APIs document filter
    # params we couldn't verify against a live tenant, so they stay full refresh.
    "groups": SentinelOneEndpointConfig(
        name="groups",
        path="/groups",
        partition_key="createdAt",
        page_size=100,  # groups caps `limit` lower than the usual 1000
    ),
    "sites": SentinelOneEndpointConfig(
        name="sites",
        path="/sites",
        partition_key="createdAt",
        page_size=100,
        data_key="sites",  # sites wraps the list: {"data": {"sites": [...]}}
    ),
}

ENDPOINTS = tuple(SENTINELONE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SENTINELONE_ENDPOINTS.items()
}
