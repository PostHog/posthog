import asyncio
from collections.abc import Sequence

import pyarrow as pa
import deltalake
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    first_per_pk_table,
    normalize_column_name,
    pyarrow_schema_from_arrow_exportable,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    execute_with_conflict_retry,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef


def _distinct_key_count(keys: pa.Table, key_columns: list[str]) -> int:
    """Number of distinct key tuples. Grouping handles composite keys, which
    `pyarrow.compute.count_distinct` cannot express since it takes a single array."""
    return keys.group_by(key_columns).aggregate([]).num_rows


def _partition_values(delta_table: deltalake.DeltaTable) -> list[str]:
    """Every partition value the table currently holds files for.

    `get_add_actions` returns an arro3 table rather than a pyarrow one, so it has to be
    adapted before pyarrow's accessors are available.
    """
    actions = pa.table(delta_table.get_add_actions(flatten=True))
    column = f"partition.{PARTITION_KEY}"
    if column not in actions.column_names:
        return []
    return sorted({value for value in actions.column(column).to_pylist() if value is not None})


def _dedupe(data: pa.Table, key_columns: list[str]) -> tuple[pa.Table, int]:
    deduped = first_per_pk_table(data, key_columns, keep="last")
    return deduped, data.num_rows - deduped.num_rows


async def _rewrite(
    delta_table: deltalake.DeltaTable,
    data: pa.Table,
    predicate: str | None,
    partitioned: bool,
    logger: FilteringBoundLogger,
) -> None:
    def _write() -> None:
        deltalake.write_deltalake(
            table_or_uri=delta_table,
            data=data,
            partition_by=PARTITION_KEY if partitioned else None,
            mode="overwrite",
            predicate=predicate,
        )

    await execute_with_conflict_retry(delta_table, _write, "repair_duplicate_primary_keys", logger)


async def repair_duplicate_primary_keys(
    table_ref: DeltaTableRef,
    primary_keys: Sequence[str],
    logger: FilteringBoundLogger,
) -> int:
    """Collapse rows sharing a primary key down to one, returning how many rows were dropped.

    A first sync or a rebuild writes its first chunk with an overwrite and every later chunk
    with a plain append, because there is no table to merge against when the run starts.
    Appends do no key matching, so a key the source emits in more than one chunk of that run
    lands once per chunk. Nothing downstream repairs it: a later incremental merge matches
    every copy of the key and updates them all together, which keeps the copies identical and
    leaves the row count permanently inflated without ever failing a sync.

    The probe reads only the key columns so that the common case, a table with no duplicates,
    costs one narrow column scan. Repair rewrites a single partition at a time, so peak memory
    follows the largest partition rather than the whole table.
    """
    delta_table = await table_ref.get_delta_table()
    if delta_table is None:
        return 0

    available = set(pyarrow_schema_from_arrow_exportable(delta_table.schema()).names)
    key_columns = [name for key in primary_keys if (name := normalize_column_name(key)) in available]
    if not key_columns:
        return 0

    keys = await asyncio.to_thread(lambda: delta_table.to_pyarrow_dataset().to_table(columns=key_columns))
    duplicate_rows = keys.num_rows - _distinct_key_count(keys, key_columns)
    del keys
    if duplicate_rows == 0:
        return 0

    await logger.awarning(
        "repair_duplicate_primary_keys: found duplicate primary keys, rewriting",
        duplicate_rows=duplicate_rows,
        primary_keys=key_columns,
    )

    partition_columns = list(getattr(delta_table.metadata(), "partition_columns", None) or [])
    partitioned = PARTITION_KEY in partition_columns

    dropped = 0
    if partitioned:
        for value in _partition_values(delta_table):
            data = await asyncio.to_thread(delta_table.to_pyarrow_table, partitions=[(PARTITION_KEY, "=", value)])
            deduped, partition_dropped = _dedupe(data, key_columns)
            if partition_dropped == 0:
                continue
            await _rewrite(delta_table, deduped, f"{PARTITION_KEY} = '{value}'", partitioned, logger)
            dropped += partition_dropped
    else:
        data = await asyncio.to_thread(delta_table.to_pyarrow_table)
        deduped, dropped = _dedupe(data, key_columns)
        if dropped:
            await _rewrite(delta_table, deduped, None, partitioned, logger)

    await logger.ainfo("repair_duplicate_primary_keys: dropped duplicate rows", dropped_rows=dropped)

    return dropped
