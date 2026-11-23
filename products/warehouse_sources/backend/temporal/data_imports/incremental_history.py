"""History tables for incremental syncs: a second output lane into `_history`, chosen by `cdc_table_mode`.

Each version starts at the row's incremental field value, and the lane writes versions once per run (see `history_upsert`).
"""

import asyncio
import functools
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import pyarrow as pa
import deltalake
import structlog
import pyarrow.compute as pc
from asgiref.sync import sync_to_async

from posthog.models.team import Team
from posthog.ph_client import feature_enabled_or_false

from products.warehouse_sources.backend.facade.contracts import LegacyHistoryTableError
from products.warehouse_sources.backend.facade.types import IncrementalFieldType
from products.warehouse_sources.backend.models.external_data_schema import (
    HISTORY_SEED_PENDING_KEY,
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    CAPTURE_COLUMNS,
    HISTORY_NAMING,
    HistoryNaming,
    companion_resource_name,
    history_columns,
    reserved_column_collisions,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.history_table import (
    HISTORY_STAGING_SUFFIX,
    HistoryTableNameTakenError,
    incremental_history_naming,
    registered_stamped_history_table,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import SCD2_APPEND_MODE
from products.warehouse_sources.backend.temporal.data_imports.destinations.enablement import (
    external_destination_ids_for,
    includes_the_warehouse,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import resolve_primary_keys
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta import history_upsert
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.history_upsert import (
    HistoryFinalizeResult,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import VACUUM_RETENTION
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import commit_runs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.projection import (
    filter_dwh_columns_by_enabled_columns,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import OutputLane, SourceResponse

logger = structlog.get_logger(__name__)

INCREMENTAL_HISTORY_FLAG = "dwh-incremental-history"
# A date cursor stays equal for every change made the same day, so those changes would make no version
# while the consolidated table takes each of them.
HISTORY_CURSOR_TYPES = frozenset({IncrementalFieldType.DateTime, IncrementalFieldType.Timestamp})
_VALID_FROM_TYPE = pa.timestamp("us", tz="UTC")
_SEED_BATCH_ROWS = 50_000
_MAX_SEED_HISTORY_SCAN = 2000
_VACUUM_MARGIN = timedelta(hours=1)

_TColumn = TypeVar("_TColumn")


class IncrementalHistoryUnavailableError(Exception):
    """A run can't write its history table. Non-retryable: a retry fails the same way."""


def incremental_history_refusal(*, incremental_field: str | None, incremental_field_type: str | None) -> str | None:
    if not incremental_field or incremental_field_type not in HISTORY_CURSOR_TYPES:
        return (
            "A history table needs an incremental field that holds a date and time, "
            "so each version can say when the row changed."
        )
    return None


def is_incremental_history_enabled_for_team(team: Team) -> bool:
    return feature_enabled_or_false(
        INCREMENTAL_HISTORY_FLAG,
        str(team.organization_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
    )


def attach_history_lanes(
    schema: ExternalDataSchema, source_response: SourceResponse, *, destination_ids: Sequence[str] = ()
) -> None:
    """Add the history lane. With the flag off, a `both` run skips it and a history-only run fails."""
    if not (schema.is_incremental and schema.keeps_history):
        return
    history_only = schema.cdc_table_mode == "cdc_only"
    if not is_incremental_history_enabled_for_team(schema.team):
        if history_only:
            raise IncrementalHistoryUnavailableError(
                f"{schema.name} keeps only a history table, and history tables for incremental syncs are turned off"
            )
        logger.warning("incremental_history_lane_skipped", schema_id=str(schema.id), reason="flag_off")
        return
    if not includes_the_warehouse(schema.team_id, destination_ids):
        raise IncrementalHistoryUnavailableError(
            f"{schema.name} keeps a history table, which lives in the PostHog warehouse, but it doesn't sync there"
        )
    if history_only and external_destination_ids_for(schema.team_id, destination_ids):
        # The run's first lane delivers to the destinations, and in this mode that lane is the history table.
        raise IncrementalHistoryUnavailableError(
            f"{schema.name} keeps only a history table, which can't sync to other destinations. "
            "Keep both tables to sync it there too."
        )
    if source_response.lanes or source_response.replace_scope is not None:
        raise IncrementalHistoryUnavailableError(
            f"{schema.name} keeps a history table, but its source replaces rows instead of merging them by key"
        )
    if not resolve_primary_keys(schema, source_response):
        raise IncrementalHistoryUnavailableError(f"{schema.name} keeps a history table, which needs a primary key")
    if schema.incremental_field is None:
        raise IncrementalHistoryUnavailableError(
            f"{schema.name} keeps a history table, which needs an incremental field"
        )
    try:
        naming = incremental_history_naming(schema)
    except (LegacyHistoryTableError, HistoryTableNameTakenError) as e:
        raise IncrementalHistoryUnavailableError(str(e)) from e
    history_lane = OutputLane(
        name=companion_resource_name(schema.name, naming),
        cdc_write_mode=SCD2_APPEND_MODE,
        # One stream bills once: the consolidated lane's rows when it runs, else the history lane's.
        billable=history_only,
        transform=functools.partial(
            stamp_history_batch,
            schema_name=schema.name,
            cursor=normalize_column_name(schema.incremental_field),
            naming=naming,
            tracked_since=datetime.now(UTC),
        ),
    )
    if history_only:
        source_response.lanes = [history_lane]
        source_response.name = history_lane.name
    else:
        source_response.lanes = [OutputLane(name=source_response.name), history_lane]


def stamp_history_batch(
    table: pa.Table, *, schema_name: str, cursor: str, naming: HistoryNaming, tracked_since: datetime
) -> pa.Table:
    """Add `valid_from` from the cursor, or the run's time for a row without one, so a reload versions it again."""
    taken = reserved_column_collisions(table.column_names, history_columns(naming))
    if taken:
        raise IncrementalHistoryUnavailableError(
            f"{schema_name} has source column(s) {taken}, which the history table uses itself. "
            "Stop syncing or rename them, or keep the consolidated table only."
        )
    values = table.column(cursor)
    # Some sources declare an epoch-number cursor as a date and time, and a cast would read it as microseconds.
    # A date-only cursor stays equal for every change made the same day (see `HISTORY_CURSOR_TYPES`).
    if not (
        pa.types.is_timestamp(values.type) or pa.types.is_string(values.type) or pa.types.is_large_string(values.type)
    ):
        raise IncrementalHistoryUnavailableError(
            f"{schema_name} keeps a history table, which needs its incremental field {cursor} to hold a date and "
            f"time, but the source sends {values.type}"
        )
    try:
        try:
            valid_from = pc.cast(values, _VALID_FROM_TYPE)
        except pa.ArrowInvalid:
            # A text cursor without a zone offset is read as UTC, as the incremental filter reads it.
            valid_from = pc.cast(pc.cast(values, pa.timestamp("us")), _VALID_FROM_TYPE)
    except pa.ArrowInvalid as e:
        raise IncrementalHistoryUnavailableError(
            f"{schema_name} keeps a history table, which needs every value of its incremental field {cursor} to be "
            f"a date and time it can read: {e}"
        ) from e
    valid_from = valid_from.fill_null(pa.scalar(tracked_since, _VALID_FROM_TYPE))
    return table.append_column(pa.field(naming.valid_from, _VALID_FROM_TYPE), valid_from)


def registered_history_columns(
    columns: Mapping[str, _TColumn],
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None,
    incremental_field: str | None,
) -> dict[str, _TColumn]:
    """The synced columns plus the history columns. The table keeps an unselected column's past values, so only its
    registration can hide it."""
    synced = filter_dwh_columns_by_enabled_columns(dict(columns), enabled_columns, primary_keys, incremental_field)
    kept = HISTORY_NAMING.stamped_columns | CAPTURE_COLUMNS
    return {name: column for name, column in columns.items() if name in synced or name in kept}


def incremental_history_table(schema: ExternalDataSchema) -> DataWarehouseTable | None:
    """The registered `_history` table of a schema that doesn't sync with CDC, also after it stopped keeping history."""
    return None if schema.is_cdc else registered_stamped_history_table(schema)


def stages_history(cdc_write_mode: str | None, sync_type: str | None) -> bool:
    """Whether a batch belongs to an incremental history lane. CDC history still closes per batch."""
    return cdc_write_mode == SCD2_APPEND_MODE and sync_type != "cdc"


def _staging_ref(table: DeltaTableRef) -> DeltaTableRef:
    # The staging table sits in the schema's folder and is never registered, so no query sees it.
    return DeltaTableRef(
        resource_name=f"{table.resource_name}{HISTORY_STAGING_SUFFIX}", job=table.job, logger=table.logger
    )


async def stage_history_batch(
    table: DeltaTableRef, data: pa.Table, *, primary_keys: Sequence[str], run_uuid: str, batch_index: int
) -> deltalake.DeltaTable:
    staging = _staging_ref(table)
    await history_upsert.stage(
        staging,
        data,
        key_columns=primary_keys,
        naming=HISTORY_NAMING,
        run_uuid=run_uuid,
        batch_index=batch_index,
    )
    staged = await staging.get_delta_table()
    if staged is None:
        raise ValueError(f"The staging table of {table.resource_name} is missing after an append")
    return staged


async def finalize_history_lane(
    table: DeltaTableRef,
    primary_keys: Sequence[str],
    *,
    schema: ExternalDataSchema,
    run_uuid: str,
    batch_index: int,
) -> HistoryFinalizeResult | None:
    """Write the run's staged rows as versions, at the run's final batch. None when the lane staged nothing.

    When history was turned on for a table that already holds rows, the main table's rows are staged
    too and become the first versions. The request stays until the finalize completes, and a retry
    stages them again, which makes no second version.
    """
    seed_requested_at = schema.sync_type_config.get(HISTORY_SEED_PENDING_KEY)
    if isinstance(seed_requested_at, str):
        await _stage_seed(table, schema, primary_keys, run_uuid, datetime.fromisoformat(seed_requested_at))
    result = await history_upsert.finalize(
        table,
        _staging_ref(table),
        key_columns=primary_keys,
        naming=HISTORY_NAMING,
        commit_metadata={"run_uuid": run_uuid, "batch_index": str(batch_index)},
    )
    if isinstance(seed_requested_at, str):
        await sync_to_async(_clear_seed_request)(schema, seed_requested_at)
    return result


def _clear_seed_request(schema: ExternalDataSchema, requested_at: str) -> None:
    def _clear(config: dict) -> None:
        # History turned off and on again during the run asks for a seed of its own.
        if config.get(HISTORY_SEED_PENDING_KEY) == requested_at:
            config.pop(HISTORY_SEED_PENDING_KEY)

    update_sync_type_config_keys(schema.id, schema.team_id, mutate=_clear)


async def _stage_seed(
    table: DeltaTableRef,
    schema: ExternalDataSchema,
    primary_keys: Sequence[str],
    run_uuid: str,
    requested_at: datetime,
) -> None:
    """Stage the main table's rows as they were before this run, each version starting at its cursor.

    A row without a cursor starts when history was turned on.
    """
    main = DeltaTableRef(resource_name=schema.name, job=table.job, logger=table.logger)
    rows = await _rows_before_run(main, run_uuid)
    if rows is None:
        return
    if schema.incremental_field is None:
        raise IncrementalHistoryUnavailableError(
            f"{schema.name} keeps a history table, which needs an incremental field"
        )
    stamp = functools.partial(
        stamp_history_batch,
        schema_name=schema.name,
        cursor=normalize_column_name(schema.incremental_field),
        naming=HISTORY_NAMING,
        tracked_since=requested_at,
    )
    dataset = rows.to_pyarrow_dataset()
    columns = [name for name in dataset.schema.names if name != PARTITION_KEY]

    def _tables() -> Iterator[pa.Table]:
        scanner = dataset.scanner(
            columns=columns, batch_size=_SEED_BATCH_ROWS, batch_readahead=1, fragment_readahead=1, use_threads=False
        )
        for batch in scanner.to_batches():
            if batch.num_rows:
                yield stamp(pa.Table.from_batches([batch]))

    staged = await history_upsert.stage_seed(
        _staging_ref(table),
        stamp(dataset.schema.empty_table().select(columns)).schema,
        _tables(),
        key_columns=primary_keys,
        naming=HISTORY_NAMING,
        # Its own tag, so the redelivery check of the run's real batches never finds the seed.
        run_uuid=f"{run_uuid}-seed",
        batch_index=0,
    )
    await table.logger.ainfo("history_seed_staged", rows=staged, main_table_version=rows.version())


async def _rows_before_run(main: DeltaTableRef, run_uuid: str) -> deltalake.DeltaTable | None:
    """The main table at its last version before this run wrote to it. None when this run created it.

    Falls back to the current version when the run's first write is old enough that a vacuum may have
    removed the files it replaced.
    """
    current = await main.get_delta_table()
    if current is None:
        return None
    commits = await asyncio.to_thread(current.history, _MAX_SEED_HISTORY_SCAN)
    first: dict[str, Any] | None = None
    # Newest first. The pipeline lock keeps other runs from writing while this one loads.
    for commit in commits:
        runs = commit_runs(commit)
        if run_uuid in runs:
            first = commit
        elif runs:
            break
    if first is None:
        return current
    version = int(first["version"])
    if len(commit_runs(first)) == 1:
        version -= 1
    if version < 0:
        return None
    written_at = datetime.fromtimestamp(int(first["timestamp"]) / 1000, UTC)
    if datetime.now(UTC) - written_at > VACUUM_RETENTION - _VACUUM_MARGIN:
        await main.logger.awarning("history_seed_reads_current_version", run_first_write=written_at.isoformat())
        return current
    return await asyncio.to_thread(
        deltalake.DeltaTable,
        await main.get_table_uri(),
        version=version,
        storage_options=main.get_storage_options(),
    )
