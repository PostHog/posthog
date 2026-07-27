"""Compute per-column data statistics for a synced warehouse table.

Runs as a fire-and-forget child workflow after a sync completes. It gives the AI agent a quantitative
profile of each column — how null-heavy it is, its value range, and the table's size — so it writes
better queries (handles/avoids null-heavy columns, bounds filters and time windows correctly).

Stats come from the Delta transaction log's per-file statistics (`num_records`, `null_count`, `min`,
`max`), aggregated across the snapshot's live files. This reads the *log*, never the data, so it is
exact, whole-table, correct for full-refresh/append/incremental-upsert (live add-actions reflect the
current files), and scales to any table size. Results land in `WarehouseColumnStatistics`, fully
system-owned and overwritten on each run. To avoid re-profiling an hourly-syncing table every hour,
a row computed within `MIN_RECOMPUTE_INTERVAL` is left alone.
"""

import os
import json
import uuid
import dataclasses
from datetime import timedelta
from typing import Any

from django.utils import timezone

import structlog
import posthoganalytics
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater

from products.warehouse_sources.backend.models.column_statistics import WarehouseColumnStatistics
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.models.util import clean_type

logger = structlog.get_logger(__name__)

STATISTICS_FEATURE_FLAG = "data-warehouse-column-statistics"
# Cap profiling to once a day per table — an hourly-syncing table doesn't need re-profiling every hour,
# and Delta-log stats only move materially over longer windows. Env-overridable for ops.
MIN_RECOMPUTE_INTERVAL = timedelta(hours=int(os.getenv("WAREHOUSE_STATS_MIN_RECOMPUTE_INTERVAL_HOURS", "24")))

# Product-analytics events — query these to track statistics volume, columns profiled, skips, and errors.
EVENT_STARTED = "data warehouse table statistics started"
EVENT_COMPLETED = "data warehouse table statistics completed"
EVENT_ERROR = "data warehouse table statistics error"


@dataclasses.dataclass(frozen=True)
class ComputeTableStatisticsInputs:
    team_id: int
    schema_id: uuid.UUID

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"team_id": self.team_id, "schema_id": str(self.schema_id)}


def statistics_enabled(team: Team) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                STATISTICS_FEATURE_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        capture_exception(e)
        return False


def capture_statistics_event(team: Team, event: str, properties: dict[str, Any]) -> None:
    """Best-effort product-analytics capture, attributed to the team's org/project groups.

    Telemetry must never break the activity, so all failures are swallowed (and reported to Sentry).
    """
    try:
        posthoganalytics.capture(
            distinct_id=str(team.uuid),
            event=event,
            properties={**properties, "team_id": team.id},
            groups={"organization": str(team.organization_id), "project": str(team.id)},
        )
    except Exception as e:
        capture_exception(e)


def _column_type(definition: Any) -> str:
    """Source-agnostic ClickHouse type string from a `DataWarehouseTable.columns` entry.

    Handles both the dict shape (`{"clickhouse": ...}`) and the legacy plain-string shape.
    """
    if isinstance(definition, dict):
        return definition.get("clickhouse") or definition.get("hogql") or ""
    return definition or ""


@dataclasses.dataclass
class _ColumnStat:
    column_type: str
    null_count: int | None
    min_value: str | None
    max_value: str | None
    has_min_max: bool


def _aggregate_add_action_stats(add_actions: Any, columns: dict[str, Any]) -> tuple[int, dict[str, _ColumnStat]]:
    """Aggregate the Delta log's per-file stats into per-column whole-table stats.

    `add_actions` is `DeltaTable.get_add_actions(flatten=True)` — one row per live file, with
    `num_records` and (where the log carries stats) `null_count.<col>`, `min.<col>`, `max.<col>`.
    Returns `(row_count, {column_name: _ColumnStat})`. Columns with no log stats get `has_min_max=False`.
    """
    import pyarrow as pa  # noqa: PLC0415 — heavy dep kept off this module's flag-check import path

    # deltalake>=1.x returns an arro3 RecordBatch (no `to_pydict`); pa.table() normalizes both that
    # (via the Arrow C interface) and an already-pyarrow input to a pyarrow Table we can read as a dict.
    data = pa.table(add_actions).to_pydict()
    row_count = sum(n for n in data.get("num_records", []) if n is not None)

    result: dict[str, _ColumnStat] = {}
    for name, definition in (columns or {}).items():
        null_key, min_key, max_key = f"null_count.{name}", f"min.{name}", f"max.{name}"

        # `null_count = None` (unknown) when the log carried no per-file null counts — either the key is
        # absent or every file's value is None. Mirrors the min/max guard below; a real zero stays 0.
        null_values = [v for v in data.get(null_key, []) if v is not None] if null_key in data else []
        null_count = sum(null_values) if null_values else None

        mins = [v for v in data.get(min_key, []) if v is not None] if min_key in data else []
        maxs = [v for v in data.get(max_key, []) if v is not None] if max_key in data else []
        min_value = str(min(mins)) if mins else None
        max_value = str(max(maxs)) if maxs else None
        has_min_max = bool(mins or maxs)

        result[name] = _ColumnStat(
            column_type=clean_type(_column_type(definition)) or "unknown",
            null_count=null_count,
            min_value=min_value,
            max_value=max_value,
            has_min_max=has_min_max,
        )
    return row_count, result


def _most_recent_computed_at(existing: dict[str, WarehouseColumnStatistics]) -> Any | None:
    times = [s.computed_at for s in existing.values() if s.computed_at is not None]
    return max(times) if times else None


def compute_table_statistics_sync(team_id: int, schema_id: uuid.UUID) -> dict[str, Any]:
    """Compute and persist per-column statistics for one warehouse table. Safe to re-run."""
    # Lazy: DeltaTableHelper drags deltalake/pyarrow/dlt — keep them off the flag-check import path that
    # create_external_data_job_model_activity uses (it only imports statistics_enabled).
    from asgiref.sync import async_to_sync  # noqa: PLC0415

    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_table_helper import (  # noqa: PLC0415
        DeltaTableHelper,
    )

    log = logger.bind(team_id=team_id, schema_id=str(schema_id))

    team = Team.objects.select_related("organization").only("id", "uuid", "organization_id").get(id=team_id)
    event_props: dict[str, Any] = {"schema_id": str(schema_id)}

    def emit_completed(status: str, **props: Any) -> None:
        capture_statistics_event(team, EVENT_COMPLETED, {"status": status, **event_props, **props})

    if not statistics_enabled(team):
        emit_completed("skipped", reason="flag_disabled")
        return {"status": "skipped", "reason": "flag_disabled"}

    schema = (
        ExternalDataSchema.objects.select_related("source", "table")
        .filter(team_id=team_id, deleted=False)
        .get(id=schema_id)
    )
    table = schema.table
    event_props["source_type"] = schema.source.source_type
    event_props["schema_name"] = schema.name
    if table is None:
        emit_completed("skipped", reason="no_table")
        return {"status": "skipped", "reason": "no_table"}
    event_props["table_id"] = str(table.id)

    existing = {
        stat.column_name: stat for stat in WarehouseColumnStatistics.objects.for_team(team_id).filter(table_id=table.id)
    }
    latest = _most_recent_computed_at(existing)
    if latest is not None and timezone.now() - latest < MIN_RECOMPUTE_INTERVAL:
        emit_completed("skipped", reason="computed_recently")
        return {"status": "skipped", "reason": "computed_recently"}

    capture_statistics_event(team, EVENT_STARTED, event_props)

    # Locate the committed Delta table. folder_path is schema-derived, so any job for this schema works;
    # resource_name mirrors what the pipeline used to name the Delta folder.
    job = ExternalDataJob.objects.filter(team_id=team_id, schema_id=schema_id).order_by("-created_at").first()
    if job is None:
        emit_completed("skipped", reason="no_job")
        return {"status": "skipped", "reason": "no_job"}

    resource_name = schema.resolved_s3_folder_name or schema.name
    delta_table_helper = DeltaTableHelper(resource_name=resource_name, job=job, logger=log)
    delta_table = async_to_sync(delta_table_helper.get_delta_table)()
    if delta_table is None:
        emit_completed("skipped", reason="no_delta_table")
        return {"status": "skipped", "reason": "no_delta_table"}

    delta_version = delta_table.version()
    add_actions = delta_table.get_add_actions(flatten=True)
    if add_actions.num_rows == 0:
        emit_completed("skipped", reason="no_files")
        return {"status": "skipped", "reason": "no_files"}

    columns = table.columns or {}
    if not columns:
        emit_completed("skipped", reason="no_columns")
        return {"status": "skipped", "reason": "no_columns"}

    row_count, stats_by_column = _aggregate_add_action_stats(add_actions, columns)

    for column_name, stat in stats_by_column.items():
        _upsert_statistics(team, table, column_name, row_count, stat, delta_version)

    log.info("warehouse_statistics.done", columns=len(stats_by_column), row_count=row_count)
    emit_completed("done", columns=len(stats_by_column), row_count=row_count, delta_version=delta_version)
    return {"status": "done", "columns": len(stats_by_column), "row_count": row_count}


def _upsert_statistics(
    team: Team,
    table: DataWarehouseTable,
    column_name: str,
    row_count: int,
    stat: _ColumnStat,
    delta_version: int,
) -> None:
    """Persist (overwrite) one column's stats. Stats are wholly system-owned, so a plain upsert is correct."""
    null_fraction = (stat.null_count / row_count) if (stat.null_count is not None and row_count > 0) else None
    WarehouseColumnStatistics.objects.for_team(team.id).update_or_create(
        table=table,
        column_name=column_name,
        defaults={
            "team": team,
            "column_type": stat.column_type,
            "row_count": row_count,
            "null_count": stat.null_count,
            "null_fraction": null_fraction,
            "min_value": stat.min_value,
            "max_value": stat.max_value,
            "has_min_max": stat.has_min_max,
            "computed_at": timezone.now(),
            "computed_for_delta_version": delta_version,
            "stats_basis": "delta_log",
        },
    )


@activity.defn
async def compute_table_statistics_activity(inputs: ComputeTableStatisticsInputs) -> dict[str, Any]:
    """Activity wrapper. Heartbeats and runs the (sync) computation off the event loop."""
    async with Heartbeater():
        try:
            return await database_sync_to_async(compute_table_statistics_sync, thread_sensitive=False)(
                inputs.team_id, inputs.schema_id
            )
        except Exception as e:
            capture_exception(e)
            try:
                posthoganalytics.capture(
                    distinct_id=f"team-{inputs.team_id}",
                    event=EVENT_ERROR,
                    properties={"team_id": inputs.team_id, "schema_id": str(inputs.schema_id), "error": str(e)},
                    groups={"project": str(inputs.team_id)},
                )
            except Exception as capture_error:
                capture_exception(capture_error)
            raise


@workflow.defn(name="compute-warehouse-table-statistics")
class ComputeTableStatisticsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ComputeTableStatisticsInputs:
        loaded = json.loads(inputs[0])
        return ComputeTableStatisticsInputs(team_id=loaded["team_id"], schema_id=uuid.UUID(loaded["schema_id"]))

    @workflow.run
    async def run(self, inputs: ComputeTableStatisticsInputs) -> None:
        await workflow.execute_activity(
            compute_table_statistics_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
