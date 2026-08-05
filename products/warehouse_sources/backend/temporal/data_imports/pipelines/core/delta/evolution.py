import asyncio
import dataclasses
from collections.abc import Iterator

import pyarrow as pa
import deltalake
import pyarrow.compute as pc
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    COLUMN_TYPE_CHANGED_REMEDY,
    DeltaColumnWideningRequired,
    SchemaColumnTypeChangedException,
    evolve_pyarrow_schema,
    pyarrow_schema_from_arrow_exportable,
)

# Rows per streamed record batch while converting a column's type. Bounds peak memory
# independently of table size, the same way the repartitioner's rewrite does.
WIDENING_REWRITE_BATCH_SIZE = 50_000

# Largest table (at rest, from the Delta log) whose columns are converted during a sync. The
# conversion blocks the batch that triggered it, and the loader holds a batch lease while it runs,
# so this bounds that pause: a few GB of parquet streams through in well under a minute. A bigger
# table fails with the reset message instead of stalling every batch behind a long rewrite.
MAX_WIDENING_REWRITE_BYTES = 2 * 1024**3


@dataclasses.dataclass(frozen=True, kw_only=True)
class AlignedBatch:
    """A batch aligned to the Delta table's schema, plus any stored columns widened to get there."""

    table: pa.Table
    widened_columns: dict[str, str]


async def evolve_delta_schema(delta_table: deltalake.DeltaTable, schema: pa.Schema) -> deltalake.DeltaTable:
    """Add any columns `schema` carries that the table doesn't have yet.

    Kept out of `delta/ops.py` so the `dlt` import stays off the maintenance-only import path.

    Columns added here always predate their own addition: every file the table already
    holds was written without this column, so it must tolerate absent values on those
    rows. Forcing nullable regardless of the incoming batch's own nullability (which
    reflects only whether *this* batch happened to contain nulls) is what lets a later
    `optimize.compact()` read those old files at all — a non-nullable add otherwise fails
    compaction with "Non-nullable column '<name>' is missing from the physical schema".
    """
    delta_table_schema = pyarrow_schema_from_arrow_exportable(delta_table.schema())

    new_fields = [
        deltalake.Field.from_arrow(field.with_nullable(True))
        for field in ensure_delta_compatible_arrow_schema(schema)
        if field.name not in delta_table_schema.names
    ]
    if new_fields:
        await asyncio.to_thread(delta_table.alter.add_columns, new_fields)

    return delta_table


async def align_batch_to_delta_schema(
    delta_table: deltalake.DeltaTable, pa_table: pa.Table, logger: FilteringBoundLogger
) -> AlignedBatch:
    """Align `pa_table` to the Delta table, converting stored columns first when they're too narrow.

    A source that starts sending wider values for a column (a cost column that only held whole
    numbers now carrying fractions, an upstream `integer` widened to `bigint`) otherwise fails the
    same cast on every run forever. Where the stored column can be converted without losing any of
    its own values, convert it and align against the new schema; where it can't, the original
    terminal error stands.
    """
    try:
        return AlignedBatch(table=evolve_pyarrow_schema(pa_table, delta_table.schema()), widened_columns={})
    except DeltaColumnWideningRequired as e:
        widened = await widen_delta_columns(delta_table, e.promotions, logger)
        return AlignedBatch(table=evolve_pyarrow_schema(pa_table, delta_table.schema()), widened_columns=widened)


async def widen_delta_columns(
    delta_table: deltalake.DeltaTable, promotions: dict[str, pa.DataType], logger: FilteringBoundLogger
) -> dict[str, str]:
    """Convert `promotions`' stored columns to their wider types, in place, from what's in S3.

    delta-rs has no ALTER COLUMN TYPE and its own schema merge would quietly cast the incoming
    values down to the stored type instead (dropping the fractions that made the column too narrow
    in the first place), so the table is streamed through a single atomic overwrite commit that
    rewrites every file under the wider schema. Nothing is committed until the whole stream lands,
    so a crash or a value that doesn't survive the conversion leaves the table exactly as it was.

    Returns the columns' new types keyed by name, for logging.
    """
    stored_schema = pyarrow_schema_from_arrow_exportable(delta_table.schema())
    target_schema = stored_schema
    for column_name, target_type in promotions.items():
        index = target_schema.get_field_index(column_name)
        if index >= 0:
            target_schema = target_schema.set(index, target_schema.field(index).with_type(target_type))

    if target_schema == stored_schema:
        return {}

    table_bytes = await asyncio.to_thread(_delta_table_bytes, delta_table)
    if table_bytes > MAX_WIDENING_REWRITE_BYTES:
        raise SchemaColumnTypeChangedException(
            f"Source column type changed: {_describe(promotions)} no longer fits the type stored for it, and this "
            f"table is too large to convert during a sync ({table_bytes / 1024**3:.1f} GB). "
            f"{COLUMN_TYPE_CHANGED_REMEDY}"
        )

    await logger.ainfo(
        "widening stored delta columns so the source's new values fit",
        columns={name: str(type_) for name, type_ in promotions.items()},
        table_bytes=table_bytes,
    )

    cast_failure: Exception | None = None

    def rewrite() -> None:
        nonlocal cast_failure
        dataset = delta_table.to_pyarrow_dataset()
        reader = dataset.scanner(batch_size=WIDENING_REWRITE_BATCH_SIZE).to_reader()
        partition_columns = list(delta_table.metadata().partition_columns or [])

        def batches() -> Iterator[pa.RecordBatch]:
            nonlocal cast_failure
            for batch in reader:
                try:
                    yield _cast_batch(batch, target_schema)
                except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as e:
                    # Raising aborts the write before it commits, so the table keeps its old type
                    # and its old values. Recorded because delta-rs re-raises it as an opaque
                    # DeltaError that the caller can't otherwise tell apart from an S3 failure.
                    cast_failure = e
                    raise

        deltalake.write_deltalake(
            delta_table,
            pa.RecordBatchReader.from_batches(target_schema, batches()),
            mode="overwrite",
            schema_mode="overwrite",
            partition_by=partition_columns or None,
        )
        delta_table.update_incremental()

    try:
        await asyncio.to_thread(rewrite)
    except Exception:
        if cast_failure is None:
            raise
        # Values already in the column can't be represented in the wider type (an integer past the
        # range a double holds exactly). Converting them would change the data, so it stays terminal.
        raise SchemaColumnTypeChangedException(
            f"Source column type changed: {_describe(promotions)} no longer fits the type stored for it, and the "
            f"rows already stored can't be converted without changing their values. {COLUMN_TYPE_CHANGED_REMEDY}"
        ) from cast_failure

    widened = {name: str(target_schema.field(name).type) for name in promotions if name in target_schema.names}
    await logger.ainfo("widened stored delta columns", columns=widened)
    return widened


def _describe(promotions: dict[str, pa.DataType]) -> str:
    return ", ".join(f"'{name}'" for name in promotions)


def _delta_table_bytes(delta_table: deltalake.DeltaTable) -> int:
    """At-rest bytes of the table, read from the Delta log (no S3 LIST, no data scan)."""
    actions = delta_table.get_add_actions(flatten=True)
    if "size_bytes" not in actions.schema.names:
        return 0
    return sum(size or 0 for size in actions.column("size_bytes").to_pylist())


def _cast_batch(batch: pa.RecordBatch, schema: pa.Schema) -> pa.RecordBatch:
    """Re-type `batch` to `schema`, refusing any cast that wouldn't round-trip the values."""
    arrays: list[pa.Array] = []
    for field in schema:
        index = batch.schema.get_field_index(field.name)
        if index < 0:
            raise pa.ArrowInvalid(f"Column '{field.name}' is missing from the stored table's own data")
        column = batch.column(index)
        arrays.append(column if column.type == field.type else pc.cast(column, field.type))
    return pa.RecordBatch.from_arrays(arrays, schema=schema)
