"""History tables for incremental syncs.

An incremental schema keeps history the way a CDC schema does: its run gets a second output lane
into the `_history` table, and `cdc_table_mode` chooses the tables (consolidated, history only, or
both). Each version starts at the row's incremental field value, so a change that does not move the
cursor makes no version. The lane stages its batches and writes versions once per run, at its final
batch (see `HistoryWriter`).
"""

import functools
from collections.abc import Sequence
from datetime import UTC, datetime

import pyarrow as pa
import deltalake
import pyarrow.compute as pc

from posthog.models.team import Team
from posthog.ph_client import feature_enabled_or_false

from products.warehouse_sources.backend.facade.types import IncrementalFieldType
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    CURRENT_HISTORY_PARTITION,
    HistoryNaming,
    companion_resource_name,
    history_columns,
    history_naming_of,
    reserved_column_collisions,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCReservedColumnError
from products.warehouse_sources.backend.temporal.data_imports.cdc.history_table import kept_history_naming
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import SCD2_APPEND_MODE
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import resolve_primary_keys
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.history_writer import (
    HistoryFinalizeResult,
    HistoryWriter,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import VACUUM_RETENTION
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    execute_with_conflict_retry,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import OutputLane, SourceResponse

INCREMENTAL_HISTORY_FLAG = "dwh-incremental-history"
HISTORY_CURSOR_TYPES = frozenset(
    {IncrementalFieldType.DateTime, IncrementalFieldType.Timestamp, IncrementalFieldType.Date}
)
_STAGING_SUFFIX = "_ph_staging"
_VALID_FROM_TYPE = pa.timestamp("us", tz="UTC")


def incremental_history_refusal(
    *, sync_type: str | None, incremental_field: str | None, incremental_field_type: str | None
) -> str | None:
    """Why an incremental schema can't keep a history table with these settings, or None when it can."""
    if sync_type != ExternalDataSchema.SyncType.INCREMENTAL:
        return "A history table needs incremental or change data capture replication."
    if not incremental_field or incremental_field_type not in HISTORY_CURSOR_TYPES:
        return (
            "A history table needs an incremental field that holds a date or a time, "
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


def attach_history_lanes(schema: ExternalDataSchema, source_response: SourceResponse) -> None:
    """Add the history lane to an incremental run of a schema that keeps history."""
    if not (schema.is_incremental and schema.keeps_history):
        return
    if (
        source_response.lanes
        or source_response.replace_scope is not None
        or not resolve_primary_keys(schema, source_response)
    ):
        raise ValueError(
            f"{schema.name} keeps a history table, which needs a primary key and a source that merges rows by it"
        )
    naming = kept_history_naming(schema)
    if naming is None or schema.incremental_field is None:
        raise ValueError(f"{schema.name} keeps a history table but has no incremental field")
    history_lane = OutputLane(
        name=companion_resource_name(schema.name, naming),
        cdc_write_mode=SCD2_APPEND_MODE,
        # One stream bills once: the consolidated lane's rows when it runs, else the history lane's.
        billable=schema.cdc_table_mode == "cdc_only",
        transform=functools.partial(
            stamp_history_batch,
            cursor=normalize_column_name(schema.incremental_field),
            naming=naming,
            tracked_since=datetime.now(UTC),
        ),
    )
    if schema.cdc_table_mode == "cdc_only":
        source_response.lanes = [history_lane]
        source_response.name = history_lane.name
    else:
        source_response.lanes = [OutputLane(name=source_response.name), history_lane]


def stamp_history_batch(table: pa.Table, *, cursor: str, naming: HistoryNaming, tracked_since: datetime) -> pa.Table:
    """Add `valid_from` from the cursor. A row without a cursor value starts at the run that first saw it."""
    taken = reserved_column_collisions(table.column_names, history_columns(naming))
    if taken:
        raise CDCReservedColumnError(f"Source column(s) {taken} collide with the history table's validity columns")
    values = table.column(cursor)
    try:
        valid_from = pc.cast(values, _VALID_FROM_TYPE)
    except pa.ArrowInvalid:
        # A text cursor without a zone offset is read as UTC, as the incremental filter reads it.
        valid_from = pc.cast(pc.cast(values, pa.timestamp("us")), _VALID_FROM_TYPE)
    valid_from = valid_from.fill_null(pa.scalar(tracked_since, _VALID_FROM_TYPE))
    return table.append_column(pa.field(naming.valid_from, _VALID_FROM_TYPE), valid_from)


def stages_history(cdc_write_mode: str | None, sync_type: str | None) -> bool:
    """Whether a batch belongs to an incremental history lane. CDC history still closes per batch."""
    return cdc_write_mode == SCD2_APPEND_MODE and sync_type != "cdc"


def _staging_ref(table: DeltaTableRef) -> DeltaTableRef:
    # The staging table sits in the schema's folder and is never registered, so no query sees it.
    return DeltaTableRef(resource_name=f"{table.resource_name}{_STAGING_SUFFIX}", job=table.job, logger=table.logger)


def _history_writer(
    table: DeltaTableRef, staging: DeltaTableRef, primary_keys: Sequence[str], naming: HistoryNaming
) -> HistoryWriter:
    return HistoryWriter(
        table,
        staging,
        primary_keys=primary_keys,
        valid_from_column=naming.valid_from,
        valid_to_column=naming.valid_to,
        partition_column=naming.partition_column,
        current_partition=CURRENT_HISTORY_PARTITION,
    )


async def stage_history_batch(
    table: DeltaTableRef, data: pa.Table, *, primary_keys: Sequence[str], run_uuid: str, batch_index: int
) -> deltalake.DeltaTable:
    """Stage one batch of a history lane, and return the staging table it went to."""
    staging = _staging_ref(table)
    writer = _history_writer(table, staging, primary_keys, history_naming_of(data.column_names))
    await writer.append(data, run_uuid=run_uuid, batch_index=batch_index)
    staged = await staging.get_delta_table()
    if staged is None:
        raise ValueError(f"The staging table of {table.resource_name} is missing after an append")
    return staged


async def finalize_history_lane(table: DeltaTableRef, primary_keys: Sequence[str]) -> HistoryFinalizeResult | None:
    """Write the run's staged rows as versions. None when the lane staged nothing."""
    staging = _staging_ref(table)
    staged = await staging.get_delta_table()
    if staged is None:
        return None
    naming = history_naming_of(field.name for field in staged.schema().fields)
    result = await _history_writer(table, staging, primary_keys, naming).finalize()
    # finalize only tombstones the rows it staged. The files go once they are past the retention
    # every vacuum of this product keeps, so the staging table does not grow with every run.
    await execute_with_conflict_retry(
        staged,
        lambda: staged.vacuum(
            retention_hours=int(VACUUM_RETENTION.total_seconds() // 3600),
            enforce_retention_duration=False,
            dry_run=False,
        ),
        "vacuum_history_staging",
        staging.logger,
    )
    return result
