"""Compute per-column data statistics for a synced warehouse table.

Runs as a fire-and-forget child workflow after a sync completes. It gives the AI agent a quantitative
profile of each column — how null-heavy it is, its value range, and the table's size — so it writes
better queries (handles/avoids null-heavy columns, bounds filters and time windows correctly).

Stats come from the Delta transaction log's per-file statistics (`num_records`, `null_count`, `min`,
`max`), aggregated across the snapshot's live files. This reads the *log*, never the data, so it is
exact, whole-table, correct for full-refresh/append/incremental-upsert (live add-actions reflect the
current files), and scales to any table size. Results land in `WarehouseColumnStatistics`, fully
system-owned and overwritten on each run. To avoid re-profiling an hourly-syncing table every hour,
a row computed within `MIN_RECOMPUTE_INTERVAL` is left alone, and a table whose Delta version has not
moved since the last computation is left alone until `MAX_RECOMPUTE_INTERVAL` has passed. A table that
only gained files since then folds the new files' stats into the stored rows instead of rescanning
every live file; any other change falls back to the full scan.
"""

import os
import json
import uuid
import dataclasses
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import InterfaceError, OperationalError, close_old_connections
from django.utils import timezone

import structlog
import posthoganalytics
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.db_errors import is_transient_db_error
from posthog.temporal.common.errors import NonReportableError
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater

from products.warehouse_sources.backend.models.column_statistics import WarehouseColumnStatistics
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.models.util import clean_type
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.db_retry import (
    retry_on_operational_error,
)

logger = structlog.get_logger(__name__)

STATISTICS_FEATURE_FLAG = "data-warehouse-column-statistics"
# Cap profiling to once a day per table — an hourly-syncing table doesn't need re-profiling every hour,
# and Delta-log stats only move materially over longer windows. Env-overridable for ops.
MIN_RECOMPUTE_INTERVAL = timedelta(hours=int(os.getenv("WAREHOUSE_STATS_MIN_RECOMPUTE_INTERVAL_HOURS", "24")))
# Stats derive from the Delta log at one version, so an unchanged version means unchanged stats and the
# Add-action scan (the expensive step) can be skipped. The cap still forces a recompute so a change in
# the table's registered columns, or in how stats are derived, reaches every table eventually.
MAX_RECOMPUTE_INTERVAL = timedelta(days=int(os.getenv("WAREHOUSE_STATS_MAX_RECOMPUTE_INTERVAL_DAYS", "7")))
# Each commit since the last computation is one small object-store read; past this many the full
# Add-action scan is the cheaper path again.
MAX_INCREMENTAL_COMMITS = int(os.getenv("WAREHOUSE_STATS_MAX_INCREMENTAL_COMMITS", "200"))

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


def _most_recent_computed_at(
    existing: dict[str, WarehouseColumnStatistics], current_columns: Iterable[str]
) -> Any | None:
    """Oldest `computed_at` among currently-registered columns, not the newest.

    `_upsert_statistics` writes one column at a time and only retries the whole batch on a transient
    DB error (`OperationalError`/`InterfaceError`); any other failure partway through a run leaves some
    columns stamped with a fresh `computed_at` while others still carry an earlier one. Taking the max
    would read that mixed, partially-written state as "computed recently" and skip the columns that are
    actually still stale; the min only reports fresh once every currently-registered column agrees.
    Scoped to `current_columns` so a column dropped from the table doesn't hold a stale row open
    forever and block this gate on a time that can never be reached again.
    """
    times = [s.computed_at for name, s in existing.items() if name in current_columns and s.computed_at is not None]
    return min(times) if times else None


def _most_recent_computed_version(
    existing: dict[str, WarehouseColumnStatistics], current_columns: Iterable[str]
) -> int | None:
    """Oldest `computed_for_delta_version` among currently-registered columns, not the newest.

    Same partial-write hazard as `_most_recent_computed_at`, and the same fix: a recompute that aborts
    after updating only some columns must not read as "version unchanged" just because the columns it
    did reach now carry the current version. Scoped to `current_columns` for the same reason — a column
    dropped from the table keeps its old row, which the maximum used to rely on to avoid it; the
    minimum has to exclude it explicitly instead, or a dropped column's stale version would hold this
    gate open indefinitely.
    """
    versions = [
        s.computed_for_delta_version
        for name, s in existing.items()
        if name in current_columns and s.computed_for_delta_version is not None
    ]
    return min(versions) if versions else None


def _most_recent_full_scan_at(
    existing: dict[str, WarehouseColumnStatistics], current_columns: Iterable[str]
) -> Any | None:
    """Oldest full-scan time among currently-registered columns, not the newest.

    `computed_at` is bumped on every write, fold included, so it cannot answer "how long has it been
    since a full scan last corrected drift" — `full_scan_at` is left untouched by a fold (see
    `_upsert_statistics`) so it still can. A row written before that field existed has it as None, and
    every such row predates incremental folding, so its `computed_at` was necessarily a full scan's.
    Oldest-of and scoped to `current_columns` for the same partial-write and dropped-column hazards as
    `_most_recent_computed_at`.
    """
    times = [
        (s.full_scan_at or s.computed_at)
        for name, s in existing.items()
        if name in current_columns and (s.full_scan_at or s.computed_at) is not None
    ]
    return min(times) if times else None


ReadCommitActions = Callable[[int], list[dict[str, Any]]]


def _read_commit_actions(table_uri: str, storage_options: dict[str, str], version: int) -> list[dict[str, Any]]:
    """The actions of one Delta commit, read from its `_delta_log` JSON through delta-rs's own store
    handler, so credentials and endpoints resolve exactly as they did for the table open."""
    import pyarrow.fs as pafs  # noqa: PLC0415 — heavy dep kept off this module's flag-check import path
    from deltalake.fs import DeltaStorageHandler  # noqa: PLC0415

    filesystem = pafs.PyFileSystem(DeltaStorageHandler(table_uri, storage_options))
    with filesystem.open_input_stream(f"_delta_log/{version:020d}.json") as stream:
        raw = stream.read()
    # Floats as Decimal: a decimal column's stats arrive as JSON numbers, and a float would lose
    # the digits the stored representation keeps.
    return [json.loads(line, parse_float=Decimal) for line in raw.decode().splitlines() if line.strip()]


# Actions a commit may carry without touching the live file set or the schema. Anything else
# (`remove`, `metaData`, `cdc`, or an action this list does not know) sends the recompute down the
# full path.
_NEUTRAL_ACTIONS = frozenset({"commitInfo", "txn", "protocol", "domainMetadata"})

# Bases a fold may chain onto: a full scan ("delta_log") or a previous fold ("incremental"). Both are
# rows this pipeline derived from the Delta log, so both carry numbers exact enough to fold further.
_FOLDABLE_BASES = frozenset({"delta_log", "incremental"})


class _UnparseableValue(Exception):
    """A stored or logged min/max could not be parsed as the column's current Delta type.

    Raised instead of the underlying `ValueError`/`ArithmeticError`, whose message embeds the raw
    text a builtin conversion (`int()`, `Decimal()`, `date.fromisoformat()`...) rejected — which can
    be a real customer value. This message never does, so the fold's `except Exception` handler can
    report it to logs and Sentry safely.
    """


def _parse_stored_value(delta_type: Any, text: str) -> Any:
    """Parse a stored min/max back into the Python value `str()` produced from the Add-action scan.

    Wraps a builtin conversion failure (`int()`, `Decimal()`, `date.fromisoformat()`...) in
    `_UnparseableValue` instead of letting it propagate: those exceptions embed the raw text in their
    message, which can be a real customer value, and the caller reports this exception's `str()` to
    logs and Sentry. `from None` drops the original as this exception's cause, so neither the
    chained message nor its traceback locals reach that report.
    """
    if not isinstance(delta_type, str):
        raise TypeError("nested types carry no min/max")
    try:
        if delta_type in ("byte", "short", "integer", "long"):
            return int(text)
        if delta_type in ("float", "double"):
            return float(text)
        if delta_type == "string":
            return text
        if delta_type == "boolean":
            return text == "True"
        if delta_type == "date":
            return date.fromisoformat(text)
        if delta_type in ("timestamp", "timestamp_ntz"):
            return datetime.fromisoformat(text)
        if delta_type.startswith("decimal("):
            return Decimal(text)
    except (ValueError, ArithmeticError):
        raise _UnparseableValue(f"cannot parse stored value as {delta_type}") from None
    raise TypeError(f"no stored representation for {delta_type}")


def _parse_log_value(delta_type: Any, value: Any) -> Any:
    """Coerce a commit-log stats value to the Python type the Add-action scan yields for the column,
    so a folded min/max stores the same text the full path would.

    See `_parse_stored_value` for why a conversion failure is wrapped rather than left to propagate.
    """
    if not isinstance(delta_type, str) or isinstance(value, dict | list):
        raise TypeError("nested types carry no min/max")
    try:
        if delta_type in ("byte", "short", "integer", "long"):
            return int(value)
        if delta_type in ("float", "double"):
            return float(value)
        if delta_type == "string":
            if not isinstance(value, str):
                raise TypeError("string stats must be strings")
            return value
        if delta_type == "boolean":
            if not isinstance(value, bool):
                raise TypeError("boolean stats must be booleans")
            return value
        if delta_type == "date":
            return date.fromisoformat(value)
        if delta_type in ("timestamp", "timestamp_ntz"):
            return datetime.fromisoformat(value)
        if delta_type.startswith("decimal("):
            scale = int(delta_type[len("decimal(") : -1].split(",")[1])
            return Decimal(value).quantize(Decimal(1).scaleb(-scale))
    except (ValueError, ArithmeticError):
        raise _UnparseableValue(f"cannot parse log value as {delta_type}") from None
    raise TypeError(f"no log representation for {delta_type}")


@dataclasses.dataclass(frozen=False)
class _FoldState:
    """One column's running aggregate while new commits fold into the stored statistics."""

    delta_type: Any
    null_count: int | None
    min_value: Any
    max_value: Any

    def fold(self, stats: dict[str, Any], name: str) -> None:
        # The flattened Add-action scan keys a nested column's stats by leaf (`min.payload.x`), so
        # the full path records nothing for the column itself; a partition column has no stats at
        # all. Both stay as they are.
        if not isinstance(self.delta_type, str):
            return
        null_count = stats.get("nullCount", {}).get(name)
        if isinstance(null_count, int) and not isinstance(null_count, bool):
            self.null_count = (self.null_count or 0) + null_count
        min_value = stats.get("minValues", {}).get(name)
        if min_value is not None:
            parsed = _parse_log_value(self.delta_type, min_value)
            self.min_value = parsed if self.min_value is None else min(self.min_value, parsed)
        max_value = stats.get("maxValues", {}).get(name)
        if max_value is not None:
            parsed = _parse_log_value(self.delta_type, max_value)
            self.max_value = parsed if self.max_value is None else max(self.max_value, parsed)


def _fold_commit_stats(
    *,
    existing: dict[str, WarehouseColumnStatistics],
    columns: dict[str, Any],
    delta_schema_fields: dict[str, Any],
    base_version: int,
    delta_version: int,
    read_commit_actions: ReadCommitActions,
) -> tuple[int, dict[str, _ColumnStat]] | None:
    """Fold the files added since `base_version` into the stored statistics.

    Row counts, null counts and min/max all combine file by file, so when every commit since the
    stored version only added files the stored numbers plus the new files' stats equal what the
    full scan would compute. Returns None whenever that does not hold — a removed file, a schema
    change, a file without stats, a column the stored rows do not cover — and the caller runs the
    full scan instead.
    """
    if delta_version <= base_version or delta_version - base_version > MAX_INCREMENTAL_COMMITS:
        return None

    row_counts: set[int] = set()
    states: dict[str, _FoldState] = {}
    for name in columns:
        stored = existing.get(name)
        if (
            stored is None
            or stored.computed_for_delta_version != base_version
            or stored.stats_basis not in _FOLDABLE_BASES
            or stored.row_count is None
        ):
            return None
        row_counts.add(stored.row_count)
        delta_type = delta_schema_fields.get(name)
        states[name] = _FoldState(
            delta_type=delta_type,
            null_count=stored.null_count,
            min_value=_parse_stored_value(delta_type, stored.min_value) if stored.min_value is not None else None,
            max_value=_parse_stored_value(delta_type, stored.max_value) if stored.max_value is not None else None,
        )
    if len(row_counts) != 1:
        return None
    row_count = row_counts.pop()

    for version in range(base_version + 1, delta_version + 1):
        for action in read_commit_actions(version):
            kinds = set(action) - _NEUTRAL_ACTIONS
            if not kinds:
                continue
            if kinds != {"add"}:
                return None
            add = action["add"]
            if not add.get("dataChange", True) or not add.get("stats"):
                return None
            stats = json.loads(add["stats"], parse_float=Decimal)
            num_records = stats.get("numRecords")
            if not isinstance(num_records, int) or isinstance(num_records, bool):
                return None
            row_count += num_records
            for name, state in states.items():
                state.fold(stats, name)

    return row_count, {
        name: _ColumnStat(
            column_type=clean_type(_column_type(columns[name])) or "unknown",
            null_count=state.null_count,
            min_value=str(state.min_value) if state.min_value is not None else None,
            max_value=str(state.max_value) if state.max_value is not None else None,
            has_min_max=state.min_value is not None or state.max_value is not None,
        )
        for name, state in states.items()
    }


def _delta_schema_fields(delta_table: Any) -> dict[str, Any]:
    """Column name to Delta type: a string for a primitive, a dict for a nested type."""
    schema = json.loads(delta_table.schema().to_json())
    return {field["name"]: field["type"] for field in schema.get("fields", [])}


def _all_columns_have_stats(existing: dict[str, WarehouseColumnStatistics], current_columns: Iterable[str]) -> bool:
    """Whether every currently-registered column has a statistics row at all.

    The min-based staleness checks above only compare columns that already have a row; a column
    whose very first computation never landed (its upsert failed before any row was written, not
    just before its version caught up) is invisible to them entirely, so a table with such a gap
    would read as fully fresh off the other columns' timestamps and versions alone. Both skip gates
    require this to be true first, so a never-computed column always forces a recompute rather than
    waiting out the interval.
    """
    return set(current_columns) <= existing.keys()


@retry_on_operational_error
def _get_team(team_id: int) -> Team:
    return Team.objects.select_related("organization").only("id", "uuid", "organization_id").get(id=team_id)


def compute_table_statistics_sync(team_id: int, schema_id: uuid.UUID) -> dict[str, Any]:
    """Compute and persist per-column statistics for one warehouse table. Safe to re-run."""
    # Lazy: DeltaTableRef drags deltalake/pyarrow/dlt — keep them off the flag-check import path that
    # create_external_data_job_model_activity uses (it only imports statistics_enabled).
    from asgiref.sync import async_to_sync  # noqa: PLC0415

    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import (  # noqa: PLC0415
        DeltaTableRef,
    )

    log = logger.bind(team_id=team_id, schema_id=str(schema_id))

    # A plain read, so it's safe to retry outright on the Team/Organization join losing a
    # Postgres deadlock race against an unrelated writer of either table. The team can also be
    # legitimately gone by the time this fire-and-forget child workflow runs (deleted between the
    # post-import gate check and now) — that's not a bug, so skip like the other not-found cases
    # below rather than let DoesNotExist reach the activity's except block and error tracking.
    try:
        team = _get_team(team_id)
    except Team.DoesNotExist:
        log.info("warehouse_statistics.skipped", reason="team_deleted")
        return {"status": "skipped", "reason": "team_deleted"}
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
    columns = table.columns or {}

    existing = {
        stat.column_name: stat for stat in WarehouseColumnStatistics.objects.for_team(team_id).filter(table_id=table.id)
    }
    latest = _most_recent_computed_at(existing, columns)
    # Gates every skip below: a column missing a row entirely (see _all_columns_have_stats) is
    # invisible to the min-based checks, so it must not let a table with such a gap read as fresh.
    all_columns_have_stats = _all_columns_have_stats(existing, columns)
    if latest is not None and all_columns_have_stats and timezone.now() - latest < MIN_RECOMPUTE_INTERVAL:
        emit_completed("skipped", reason="computed_recently")
        return {"status": "skipped", "reason": "computed_recently"}

    capture_statistics_event(team, EVENT_STARTED, event_props)

    # Locate the committed Delta table. folder_path is schema-derived, so any job for this schema works;
    # resource_name must resolve the folder leaf the same way the loader wrote it (see
    # resolve_table_and_folder_names in pipelines/helpers.py), otherwise this reads a path that
    # does not exist and reports no statistics.
    job = ExternalDataJob.objects.filter(team_id=team_id, schema_id=schema_id).order_by("-created_at").first()
    if job is None:
        emit_completed("skipped", reason="no_job")
        return {"status": "skipped", "reason": "no_job"}
    # Reuse the already-loaded, select_related schema instead of letting job.folder_path() lazily
    # fetch job.schema on a pooled connection a transaction pooler may have dropped in the meantime.
    job.schema = schema

    resource_name = schema.resolved_s3_folder_name or schema.name
    delta_table_ref = DeltaTableRef(resource_name=resource_name, job=job, logger=log)
    delta_table = async_to_sync(delta_table_ref.get_delta_table)()
    if delta_table is None:
        emit_completed("skipped", reason="no_delta_table")
        return {"status": "skipped", "reason": "no_delta_table"}

    delta_version = delta_table.version()
    stored_version = _most_recent_computed_version(existing, columns)
    # Delta versions are only monotonic within one incarnation (see vacuum_if_stale's identical
    # caveat): reset_table() purges the log and restarts numbering at 0 for full-refresh/reset tables,
    # so a stored version ahead of the table's current one means the table was recreated since the
    # last computation. Treat that stored version as stale rather than a match, or a table whose
    # refresh always produces the same low version number would skip recomputation indefinitely.
    version_is_stale = stored_version is not None and stored_version > delta_version
    if (
        latest is not None
        and all_columns_have_stats
        and not version_is_stale
        and stored_version == delta_version
        and timezone.now() - latest < MAX_RECOMPUTE_INTERVAL
    ):
        emit_completed("skipped", reason="version_unchanged", delta_version=delta_version)
        return {"status": "skipped", "reason": "version_unchanged"}

    # Checked before the Add-action scan: a table with no registered columns writes no rows, so
    # nothing would stop the scan from repeating on every sync.
    if not columns:
        emit_completed("skipped", reason="no_columns")
        return {"status": "skipped", "reason": "no_columns"}

    folded = _fold_since_stored_version(
        delta_table=delta_table,
        storage_options=delta_table_ref.get_storage_options(),
        existing=existing,
        columns=columns,
        delta_version=delta_version,
        log=log,
    )
    if folded is not None:
        row_count, stats_by_column = folded
        basis = "incremental"
    else:
        add_actions = delta_table.get_add_actions(flatten=True)
        if add_actions.num_rows == 0:
            emit_completed("skipped", reason="no_files")
            return {"status": "skipped", "reason": "no_files"}
        row_count, stats_by_column = _aggregate_add_action_stats(add_actions, columns)
        basis = "full"

    try:
        for column_name, stat in stats_by_column.items():
            _upsert_statistics(team, table, column_name, row_count, stat, delta_version, basis)
    except (OperationalError, InterfaceError):
        # The Delta-log read above can run long enough for the Postgres connection opened by the
        # earlier metadata queries (team/schema/existing-stats) to go stale — server restart, proxy
        # idle-close — before these writes run. Django only clears a stale connection at thread
        # entry/exit, not mid-call, so the first write here is the first thing to notice. Retry once
        # after reconnecting rather than failing the whole activity and forcing Temporal to redo the
        # Delta-log read just to redo a handful of upserts.
        if not settings.TEST:
            close_old_connections()
        for column_name, stat in stats_by_column.items():
            _upsert_statistics(team, table, column_name, row_count, stat, delta_version, basis)

    log.info("warehouse_statistics.done", columns=len(stats_by_column), row_count=row_count, basis=basis)
    emit_completed("done", columns=len(stats_by_column), row_count=row_count, delta_version=delta_version, basis=basis)
    return {"status": "done", "columns": len(stats_by_column), "row_count": row_count, "basis": basis}


def _fold_since_stored_version(
    *,
    delta_table: Any,
    storage_options: dict[str, str],
    existing: dict[str, WarehouseColumnStatistics],
    columns: dict[str, Any],
    delta_version: int,
    log: Any,
) -> tuple[int, dict[str, _ColumnStat]] | None:
    """Try the incremental fold; None means the caller runs the full Add-action scan.

    Only while the last full scan is inside MAX_RECOMPUTE_INTERVAL: the periodic full scan still
    happens, so a fold that drifted (a truncated string bound, say) is corrected within that window.
    Gating on the last full scan rather than the last write matters because a fold does not reset
    the clock (see `_upsert_statistics`) — otherwise a table folding more often than that interval
    would never fall back to a full scan at all.
    """
    base_version = _most_recent_computed_version(existing, columns)
    last_full_scan = _most_recent_full_scan_at(existing, columns)
    if base_version is None or last_full_scan is None or timezone.now() - last_full_scan >= MAX_RECOMPUTE_INTERVAL:
        return None
    try:
        return _fold_commit_stats(
            existing=existing,
            columns=columns,
            delta_schema_fields=_delta_schema_fields(delta_table),
            base_version=base_version,
            delta_version=delta_version,
            read_commit_actions=lambda version: _read_commit_actions(delta_table.table_uri, storage_options, version),
        )
    except Exception as e:
        # A commit file the log retention already removed is expected; anything else is a
        # representation the fold did not anticipate, worth a look but never worth failing over.
        if not isinstance(e, FileNotFoundError):
            capture_exception(e)
        log.warning("warehouse_statistics.incremental_fold_failed", error=str(e), base_version=base_version)
        return None


def _upsert_statistics(
    team: Team,
    table: DataWarehouseTable,
    column_name: str,
    row_count: int,
    stat: _ColumnStat,
    delta_version: int,
    basis: str,
) -> None:
    """Persist (overwrite) one column's stats. Stats are wholly system-owned, so a plain upsert is correct.

    `full_scan_at` is set only for a full scan (`basis == "full"`). Leaving it out of `defaults` for a
    fold means `update_or_create` leaves the existing row's value untouched, so it keeps anchoring the
    `MAX_RECOMPUTE_INTERVAL` check in `_fold_since_stored_version` to the last real full scan, no matter
    how many folds happen in between.
    """
    null_fraction = (stat.null_count / row_count) if (stat.null_count is not None and row_count > 0) else None
    defaults: dict[str, Any] = {
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
        "stats_basis": "delta_log" if basis == "full" else "incremental",
    }
    if basis == "full":
        defaults["full_scan_at"] = timezone.now()
    WarehouseColumnStatistics.objects.for_team(team.id).update_or_create(
        table=table,
        column_name=column_name,
        defaults=defaults,
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
            # get_delta_table already re-raises known-transient object-store blips as
            # NonReportableError (see DeltaTableRef._capture_unless_transient) and intentionally
            # skips reporting them itself — don't undo that here.
            #
            # The activity interceptor (posthog/temporal/common/posthog_client.py) already skips
            # reporting a transient app-DB blip (e.g. a PgBouncer query_wait_timeout hit while
            # resolving the Team/ExternalDataSchema/ExternalDataJob rows above) via
            # is_transient_db_error — but only for exceptions that reach it unreported. The
            # unconditional capture_exception call below would report it first, so apply the same
            # classifier here to avoid double-reporting a condition nobody can act on.
            if not isinstance(e, NonReportableError) and not is_transient_db_error(e):
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
