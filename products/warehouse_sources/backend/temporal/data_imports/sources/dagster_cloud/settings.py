from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode
from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.queries import (
    ASSETS_QUERY,
    BACKFILLS_QUERY,
    RUNS_QUERY,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Dagster's runsOrError caps well below 100 in practice; 100 is a safe request size across the
# runs/backfills/assets list resolvers.
DAGSTER_CLOUD_PAGE_SIZE = 100

# "row" -> next cursor is a field read off the last result row (runId / backfill id).
# "connection" -> next cursor is the connection object's own `cursor` field (assetsOrError).
CursorMode = Literal["row", "connection"]


def _incremental_datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class DagsterCloudEndpointConfig:
    name: str
    query: str
    # Root query field wrapping the union result (e.g. "runsOrError").
    response_field: str
    # __typename of the success member of the OrError union.
    success_typename: str
    # Key on the success member holding the list of rows ("results" or "nodes").
    results_key: str
    cursor_mode: CursorMode
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Row fields carrying Dagster epoch-seconds floats, normalized to ISO-8601 UTC strings so
    # datetime partitioning and the incremental watermark can read them like every other source.
    timestamp_fields: list[str] = field(default_factory=list)
    # For cursor_mode="row": which row field to use as the next-page cursor.
    cursor_row_field: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    supports_incremental: bool = False
    # Stable creation-time field to partition by (never an updated-at style field).
    partition_key: str | None = None
    # runsOrError / partitionBackfillsOrError return newest-first with no ascending option, so the
    # rows genuinely arrive descending.
    sort_mode: SortMode = "asc"
    should_sync_default: bool = True


DAGSTER_CLOUD_ENDPOINTS: dict[str, DagsterCloudEndpointConfig] = {
    "runs": DagsterCloudEndpointConfig(
        name="runs",
        query=RUNS_QUERY,
        response_field="runsOrError",
        success_typename="Runs",
        results_key="results",
        cursor_mode="row",
        cursor_row_field="runId",
        primary_keys=["runId"],
        timestamp_fields=["creationTime", "startTime", "endTime", "updateTime"],
        # RunsFilter.updatedAfter / .createdAfter are genuine server-side epoch filters, so an
        # incremental run only fetches runs changed since the watermark. updateTime is the default
        # (a run's status advances after creation); creationTime is offered for append-style pulls.
        incremental_fields=[
            _incremental_datetime_field("updateTime"),
            _incremental_datetime_field("creationTime"),
        ],
        supports_incremental=True,
        partition_key="creationTime",
        sort_mode="desc",
    ),
    "backfills": DagsterCloudEndpointConfig(
        name="backfills",
        query=BACKFILLS_QUERY,
        response_field="partitionBackfillsOrError",
        success_typename="PartitionBackfills",
        results_key="results",
        cursor_mode="row",
        cursor_row_field="id",
        primary_keys=["id"],
        timestamp_fields=["timestamp", "endTimestamp"],
        partition_key="timestamp",
        # partitionBackfillsOrError exposes only a status filter, no timestamp filter, so an
        # "incremental" pull would still walk full history every run — ship full refresh instead.
        sort_mode="desc",
    ),
    "assets": DagsterCloudEndpointConfig(
        name="assets",
        query=ASSETS_QUERY,
        response_field="assetsOrError",
        success_typename="AssetConnection",
        results_key="nodes",
        cursor_mode="connection",
        primary_keys=["id"],
        # Catalog snapshot with no timestamp to filter or partition on — full refresh.
    ),
}

ENDPOINTS = tuple(DAGSTER_CLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DAGSTER_CLOUD_ENDPOINTS.items()
}
