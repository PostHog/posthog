"""Applies a run's replace scope before the run's first batch loads (see `ReplaceScope`)."""

from collections.abc import Callable

import structlog
from asgiref.sync import async_to_sync

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import DeltaWriter
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.messages import ExportSignalMessage
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.replace_scope import (
    ReplaceScopeRun,
    scope_from_manifest,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3 import read_parquet

logger = structlog.get_logger(__name__)


def replace_scope_applies(export_signal: ExportSignalMessage) -> bool:
    """Whether this batch deletes rows before it writes.

    Only the first batch of a fresh attempt does. A first sync or a reset writes into an empty
    table, so it has nothing to delete.
    """
    return (
        export_signal.replace_scope is not None
        and export_signal.batch_index == 0
        and not export_signal.is_resume
        and not export_signal.is_first_ever_sync
    )


def apply_replace_scope(
    export_signal: ExportSignalMessage,
    schema: ExternalDataSchema,
    delta_table_ref: DeltaTableRef,
    verify_ownership: Callable[[], None] | None,
) -> None:
    """Delete the rows of every value the scope replaces and of every value it no longer retains.

    The attempt is recorded first, so a late batch of an earlier attempt is dropped from here on.
    The deletes commit without the batch tag, so a crash before the batch's own write leaves the
    batch to load on redelivery, which deletes the same values again and finds nothing more to
    delete. The values include every file this attempt writes, so a new attempt also removes what
    a failed attempt of the same run appended.
    """
    ref = export_signal.replace_scope
    if ref is None:
        return
    ReplaceScopeRun.record(schema, export_signal.run_uuid)

    writer = DeltaWriter(delta_table_ref)
    present = async_to_sync(writer.distinct_values)(ref.column)
    log = logger.bind(
        team_id=export_signal.team_id,
        external_data_schema_id=export_signal.schema_id,
        run_uuid=export_signal.run_uuid,
        column=ref.column,
    )
    if present is None:
        # Nothing in the table names a value to compare with: the table is new, or an earlier mode
        # wrote it without the column. The source must reset such a table, so this run only appends.
        log.warning("replace_scope_skipped_column_missing")
        return

    scope = scope_from_manifest(ref.column, read_parquet(ref.manifest_path))
    to_delete = (present - scope.retained) | (present & scope.replaced)
    rows_deleted = async_to_sync(writer.delete_where)(
        ref.column,
        to_delete,
        commit_metadata={"replace_scope_run": export_signal.run_uuid},
        before_commit=verify_ownership,
    )
    log.info(
        "replace_scope_applied",
        values_in_table=len(present),
        values_replaced=len(present & scope.replaced),
        values_removed=len(present - scope.retained),
        rows_deleted=rows_deleted,
    )
