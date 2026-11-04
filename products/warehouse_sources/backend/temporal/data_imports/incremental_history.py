"""History tables for incremental syncs.

An incremental schema keeps history the way a CDC schema does: its run gets a second output lane
into the `_history` table, and `cdc_table_mode` chooses the tables (consolidated, history only, or
both). Each version starts at the row's incremental field value, so a change that does not move the
cursor makes no version. The lane stages its batches and writes versions once per run, at its final
batch (see `history_upsert`).
"""

import functools
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TypeVar

import pyarrow as pa
import deltalake
import pyarrow.compute as pc

from posthog.models.team import Team
from posthog.ph_client import feature_enabled_or_false

from products.warehouse_sources.backend.facade.contracts import LegacyHistoryTableError
from products.warehouse_sources.backend.facade.types import IncrementalFieldType
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    HISTORY_NAMING,
    HistoryNaming,
    companion_resource_name,
    history_columns,
    reserved_column_collisions,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCReservedColumnError
from products.warehouse_sources.backend.temporal.data_imports.cdc.history_table import (
    HistoryTableNameTakenError,
    history_table_name,
    incremental_history_naming,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import SCD2_APPEND_MODE
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import resolve_primary_keys
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta import history_upsert
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.history_upsert import (
    HistoryFinalizeResult,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.projection import (
    filter_dwh_columns_by_enabled_columns,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import OutputLane, SourceResponse

INCREMENTAL_HISTORY_FLAG = "dwh-incremental-history"
# A date cursor stays equal for every change made the same day, so those changes would make no version
# while the consolidated table takes each of them.
HISTORY_CURSOR_TYPES = frozenset({IncrementalFieldType.DateTime, IncrementalFieldType.Timestamp})
_STAGING_SUFFIX = "_ph_staging"
_VALID_FROM_TYPE = pa.timestamp("us", tz="UTC")

_TColumn = TypeVar("_TColumn")


class IncrementalHistoryUnavailableError(Exception):
    """A run of a schema that keeps history cannot write its history table.

    Non-retryable: the cause is the source's shape or the schema's settings, so a retry fails the same way.
    """


def incremental_history_refusal(*, incremental_field: str | None, incremental_field_type: str | None) -> str | None:
    """Why an incremental schema can't keep a history table with this field, or None when it can."""
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


def attach_history_lanes(schema: ExternalDataSchema, source_response: SourceResponse) -> None:
    """Add the history lane to an incremental run of a schema that keeps history."""
    if not (schema.is_incremental and schema.keeps_history):
        return
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
    """Add `valid_from` from the cursor. A row without a cursor value takes the time of the run that reads
    it, so each run that reads it again (a reload) makes a new version of it."""
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


def registered_history_columns(
    columns: Mapping[str, _TColumn],
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None,
    incremental_field: str | None,
) -> dict[str, _TColumn]:
    """The history table columns a query may read: the synced columns, as the main table registers them,
    plus the validity and partition columns.

    The history table keeps a column the user stopped syncing, with its past values, so only its
    registration can hide that column.
    """
    synced = filter_dwh_columns_by_enabled_columns(dict(columns), enabled_columns, primary_keys, incremental_field)
    return {
        name: column for name, column in columns.items() if name in synced or name in HISTORY_NAMING.stamped_columns
    }


def incremental_history_table(schema: ExternalDataSchema) -> DataWarehouseTable | None:
    """The registered history table of an incremental schema that keeps history, or None."""
    if not schema.is_incremental:
        return None
    name = history_table_name(schema)
    if name is None:
        return None
    return DataWarehouseTable.objects.filter(
        team_id=schema.team_id, external_data_source_id=schema.source_id, name=name, deleted=False
    ).first()


def stages_history(cdc_write_mode: str | None, sync_type: str | None) -> bool:
    """Whether a batch belongs to an incremental history lane. CDC history still closes per batch."""
    return cdc_write_mode == SCD2_APPEND_MODE and sync_type != "cdc"


def _staging_ref(table: DeltaTableRef) -> DeltaTableRef:
    # The staging table sits in the schema's folder and is never registered, so no query sees it.
    return DeltaTableRef(resource_name=f"{table.resource_name}{_STAGING_SUFFIX}", job=table.job, logger=table.logger)


async def stage_history_batch(
    table: DeltaTableRef, data: pa.Table, *, primary_keys: Sequence[str], run_uuid: str, batch_index: int
) -> deltalake.DeltaTable:
    """Stage one batch of a history lane, and return the staging table it went to."""
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
    table: DeltaTableRef, primary_keys: Sequence[str], *, run_uuid: str, batch_index: int
) -> HistoryFinalizeResult | None:
    """Write the run's staged rows as versions, at the run's final batch. None when the lane staged nothing."""
    return await history_upsert.finalize(
        table,
        _staging_ref(table),
        key_columns=primary_keys,
        naming=HISTORY_NAMING,
        commit_metadata={"run_uuid": run_uuid, "batch_index": str(batch_index)},
    )
