from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class MetaplaneEndpointConfig:
    name: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField]
    # Stable datetime field used for partitioning. Must never change for a row
    # (so `createdAt`, never `updatedAt`). `None` disables partitioning.
    partition_key: Optional[str] = None


def _created_at_incremental_field() -> list[IncrementalField]:
    return [
        {
            "label": "createdAt",
            "type": IncrementalFieldType.DateTime,
            "field": "createdAt",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


# Metaplane's public API has no list-all-monitors endpoint — monitors hang off connections
# (`/v1/monitors/connection/{connectionId}`) and evaluations hang off monitors
# (`/v1/monitors/evaluation-history/{monitorId}`), so every endpoint below except
# `connections` fans out from the connection list. Tag endpoints are excluded: they
# require tag names as input and expose no way to enumerate tags.
METAPLANE_ENDPOINTS: dict[str, MetaplaneEndpointConfig] = {
    # GET /v1/connections — one row per connected source (warehouse, BI tool, ...).
    # Single unpaginated response, no server-side time filter -> full refresh only.
    "connections": MetaplaneEndpointConfig(
        name="connections",
        primary_keys=["id"],
        incremental_fields=[],
    ),
    # GET /v1/monitors/connection/{connectionId} per connection. Monitor ids are UUIDs
    # (globally unique). No pagination or time filter -> full refresh only.
    "monitors": MetaplaneEndpointConfig(
        name="monitors",
        primary_keys=["id"],
        incremental_fields=[],
    ),
    # POST /v1/monitors/evaluation-history/{monitorId} per monitor. Evaluations carry no id
    # of their own, so the key is the injected monitorId plus the evaluation timestamp.
    # The endpoint accepts a server-side `createdAt` cursor with ASC ordering, enabling
    # incremental sync. Merge-only (no append): the cursor's inclusivity is undocumented, so
    # incremental runs may re-pull the watermark row and rely on merge to dedupe it.
    "monitor_evaluations": MetaplaneEndpointConfig(
        name="monitor_evaluations",
        primary_keys=["monitorId", "createdAt"],
        partition_key="createdAt",
        incremental_fields=_created_at_incremental_field(),
    ),
    # GET /v1/connections/{connectionId}/sync/status per connection — the latest sync
    # outcome only (no history endpoint exists), so one row per connection, full refresh.
    "connection_sync_statuses": MetaplaneEndpointConfig(
        name="connection_sync_statuses",
        primary_keys=["connectionId"],
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(METAPLANE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in METAPLANE_ENDPOINTS.items()
}
