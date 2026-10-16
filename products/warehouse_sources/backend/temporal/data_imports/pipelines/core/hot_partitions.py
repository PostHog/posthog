"""Split the over-budget partitions of a datetime table into md5 sub-buckets, in place.

Only the partitions whose sub-bucket count changes are read and written, so a table with one hot hour
rewrites that hour and not its whole history. Each partition is replaced in one Delta commit, an
overwrite with a predicate on its partition values, so every partition is either fully on the old
keys or fully on the new ones.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import deltalake
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.models.external_data_schema import (
    finalize_hot_partition_split,
    mark_hot_split_partition_done,
    stage_hot_partition_split,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.partitioning import (
    HOT_BUCKET_SEPARATOR,
    HotPartitionSplit,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition import (
    RepartitionStoppedError,
    RepartitionSupersededError,
    RepartitionTarget,
    ensure_repartition_claim,
    measure_partition_bytes,
    partition_key_from_add_path,
    rewrite_budget,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_stream import (
    SourceReader,
    StreamBudget,
    arrow_schema_of,
    plan_source_files,
    storage_filesystem,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef


# Parquet rows decode to a few times their stored size. Used only to size the writer's row groups.
_DECODED_BYTES_PER_STORED_BYTE = 4


def _bucket_keys(base: str, count: int | None) -> set[str]:
    return {f"{base}{HOT_BUCKET_SEPARATOR}{index}" for index in range(count or 0)}


class _SplitStopped(Exception):
    pass


def _rewrite_partition(
    live: deltalake.DeltaTable,
    base: str,
    old_keys: set[str],
    split: HotPartitionSplit,
    *,
    storage_options: dict[str, str],
    budget: StreamBudget,
    should_stop: Callable[[], bool] | None,
) -> int:
    """Rewrite every row of one datetime partition under `split`, in one commit. Returns the row count.

    Reads with the rewrite's bounded reader and sizes the row groups of the writer's open files from the
    same budget, so a wide hot partition cannot outgrow the worker's memory. A stop raises before the commit, so the
    partition keeps its old keys.
    """
    count = split.buckets[base]
    sources = [source for source in plan_source_files(live) if partition_key_from_add_path(source.path) in old_keys]
    if not sources:
        # The overwrite removes every file under `old_keys`, so writing nothing would delete the partition.
        raise RuntimeError(f"no data files found for hot partition {base}")
    schema = arrow_schema_of(live.schema())
    key_index = schema.get_field_index(PARTITION_KEY)
    schema = schema.set(key_index, pa.field(PARTITION_KEY, pa.string()))
    reader = SourceReader(
        filesystem=storage_filesystem(
            live.table_uri, storage_options, known_sizes={source.path: source.size for source in sources}
        ),
        schema=schema,
        batch_bytes=budget.batch_bytes,
    )
    hash_keys = [normalize_column_name(key) for key in split.hash_keys]
    hash_columns = [key for key in hash_keys if key in schema.names]
    # The writer keeps one open file per sub-bucket, so the buffer budget is shared between them.
    rows_on_disk = sum(source.num_records or 0 for source in sources)
    bytes_on_disk = sum(source.size for source in sources)
    row_bytes = max(1, bytes_on_disk * _DECODED_BYTES_PER_STORED_BYTE // max(rows_on_disk, 1))
    row_group_rows = max(1024, budget.buffer_bytes // count // row_bytes)
    rows = 0
    stopped = False

    def batches() -> Iterator[pa.RecordBatch]:
        nonlocal rows, stopped
        for _source, tables in reader.iter_sources(sources):
            for table in tables:
                if should_stop is not None and should_stop():
                    stopped = True
                    raise _SplitStopped
                hash_values = table.select(hash_columns).to_pylist()
                keys = pa.array([split.key_for(base, [row.get(key) for key in hash_keys]) for row in hash_values])
                rows += table.num_rows
                yield from table.set_column(key_index, schema.field(key_index), keys).to_batches()
        if all(source.num_records is not None for source in sources) and rows != rows_on_disk:
            raise RuntimeError(f"read {rows} rows from hot partition {base}, the log records {rows_on_disk}")

    replaced = ", ".join(f"'{key}'" for key in sorted(old_keys | _bucket_keys(base, count)))
    try:
        deltalake.write_deltalake(
            live,
            pa.RecordBatchReader.from_batches(schema, batches()),
            mode="overwrite",
            predicate=f"{PARTITION_KEY} IN ({replaced})",
            partition_by=PARTITION_KEY,
            target_file_size=budget.target_file_bytes,
            writer_properties=deltalake.WriterProperties(max_row_group_size=row_group_rows),
        )
    except Exception as e:
        # delta-rs reports an exception raised by the batch generator as its own error type.
        if stopped:
            raise RepartitionStoppedError(f"hot partition split stopped inside {base}", rows_written=0) from e
        raise
    return rows


def hot_split_landed(live: deltalake.DeltaTable, staged: dict[str, Any], saved: dict[str, Any] | None) -> bool:
    """Whether any partition of the staged split is committed, which means it has to finish.

    Each partition is replaced in one commit, so a sub-bucket key that only the staged split makes is on
    disk exactly when that partition landed. A split with no such key can be dropped safely.
    """
    staged_split = HotPartitionSplit.from_dict(staged)
    if staged_split is None:
        return False
    saved_split = HotPartitionSplit.from_dict(saved)
    present = set(measure_partition_bytes(live))
    for base, count in staged_split.buckets.items():
        saved_count = saved_split.buckets.get(base) if saved_split else None
        if (_bucket_keys(base, count) - _bucket_keys(base, saved_count)) & present:
            return True
    return False


async def split_hot_partitions_in_place(
    *,
    table_ref: DeltaTableRef,
    schema: ExternalDataSchema,
    target: RepartitionTarget,
    logger: FilteringBoundLogger,
    claim_token: str,
    should_stop: Callable[[], bool] | None = None,
    budget: StreamBudget | None = None,
) -> dict[str, Any]:
    """Apply `target.hot_split` to the live table, then save it to the schema.

    The staged marker holds the import from the first commit until the split is saved, because a merge
    in between computes keys from the old split and inserts a duplicate of every row it should update.
    The marker records each committed partition, so a resumed attempt continues with the next one.
    """
    split = HotPartitionSplit.from_dict(target.hot_split)
    if split is None:
        return {"outcome": "skipped", "reason": "empty_hot_split"}
    live = await table_ref.get_delta_table()
    if live is None:
        return {"outcome": "skipped", "reason": "no_delta_table"}
    current = HotPartitionSplit.from_dict(schema.partition_hot_split)
    staged = await asyncio.to_thread(stage_hot_partition_split, schema, split=split.to_dict(), claim_token=claim_token)
    if staged is None:
        raise RepartitionSupersededError(f"hot partition split superseded before staging schema_id={schema.id}")
    done = set(staged.get("done", []))
    budget = budget or rewrite_budget()
    storage_options = table_ref.get_storage_options()

    present = set(await asyncio.to_thread(measure_partition_bytes, live))
    partitions_split = 0
    rows_rewritten = 0
    for base, count in sorted(split.buckets.items()):
        current_count = current.buckets.get(base) if current else None
        if current_count == count or base in done:
            continue
        old_keys = ({base} | _bucket_keys(base, current_count) | _bucket_keys(base, count)) & present
        if not old_keys:
            continue
        if should_stop is not None and should_stop():
            raise RepartitionStoppedError(
                f"hot partition split stopped after {partitions_split} partitions", rows_written=rows_rewritten
            )
        await ensure_repartition_claim(schema, claim_token)
        rows = await asyncio.to_thread(
            _rewrite_partition,
            live,
            base,
            old_keys,
            split,
            storage_options=storage_options,
            budget=budget,
            should_stop=should_stop,
        )
        if not await asyncio.to_thread(mark_hot_split_partition_done, schema, partition=base, claim_token=claim_token):
            raise RepartitionSupersededError(f"hot partition split superseded after {base} schema_id={schema.id}")
        await asyncio.to_thread(live.update_incremental)
        partitions_split += 1
        rows_rewritten += rows
        await logger.ainfo(
            f"repartition: split hot partition {base} into {count} sub-buckets rows={rows} schema_id={schema.id}",
            partition=base,
            sub_buckets=count,
            rows=rows,
        )

    if not await asyncio.to_thread(
        finalize_hot_partition_split, schema, split=split.to_dict(), claim_token=claim_token
    ):
        raise RepartitionSupersededError(f"hot partition split superseded before saving schema_id={schema.id}")
    table_ref.invalidate_cached_table()
    return {
        "outcome": "completed",
        "partitions_split": partitions_split,
        "rows_rewritten": rows_rewritten,
        "hot_partitions": len(split.buckets),
    }
