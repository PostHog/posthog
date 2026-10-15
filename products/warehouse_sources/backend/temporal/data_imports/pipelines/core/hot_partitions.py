"""Split the over-budget partitions of a datetime table into md5 sub-buckets, in place.

Only the partitions whose sub-bucket count changes are read and written, so a table with one hot hour
rewrites that hour and not its whole history. Each partition is replaced in one Delta commit, an
overwrite with a predicate on its partition values, so every partition is either fully on the old
keys or fully on the new ones.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import deltalake
import pyarrow.compute as pc
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.models.external_data_schema import (
    finalize_hot_partition_split,
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
    _ensure_claim,
    measure_partition_bytes,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef


def _bucket_keys(base: str, count: int | None) -> set[str]:
    return {f"{base}{HOT_BUCKET_SEPARATOR}{index}" for index in range(count or 0)}


def _rewrite_partition(live: deltalake.DeltaTable, base: str, old_keys: set[str], split: HotPartitionSplit) -> int:
    """Rewrite every row of one datetime partition under `split`, in one commit. Returns the row count."""
    new_keys = _bucket_keys(base, split.buckets[base])
    dataset = live.to_pyarrow_dataset()
    scanner = dataset.scanner(filter=pc.field(PARTITION_KEY).isin(sorted(old_keys)))
    hash_keys = [normalize_column_name(key) for key in split.hash_keys]
    hash_columns = [key for key in hash_keys if key in dataset.schema.names]
    key_index = dataset.schema.get_field_index(PARTITION_KEY)
    output_schema = dataset.schema.set(key_index, pa.field(PARTITION_KEY, pa.string()))
    rows = 0

    def batches():
        nonlocal rows
        for batch in scanner.to_batches():
            if batch.num_rows == 0:
                continue
            hash_values = batch.select(hash_columns).to_pylist()
            keys = [split.key_for(base, [row.get(key) for key in hash_keys]) for row in hash_values]
            rows += batch.num_rows
            yield batch.set_column(key_index, pa.field(PARTITION_KEY, pa.string()), pa.array(keys, pa.string()))

    replaced = ", ".join(f"'{key}'" for key in sorted(old_keys | new_keys))
    deltalake.write_deltalake(
        live,
        pa.RecordBatchReader.from_batches(output_schema, batches()),
        mode="overwrite",
        predicate=f"{PARTITION_KEY} IN ({replaced})",
        partition_by=PARTITION_KEY,
    )
    return rows


async def split_hot_partitions_in_place(
    *,
    table_ref: DeltaTableRef,
    schema: ExternalDataSchema,
    target: RepartitionTarget,
    logger: FilteringBoundLogger,
    claim_token: str,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Apply `target.hot_split` to the live table, then save it to the schema.

    The staged marker holds the import from the first commit until the split is saved, because a merge
    in between computes keys from the old split and inserts a duplicate of every row it should update.
    A resumed attempt rewrites the changed partitions again. That is safe, because the keys depend on
    the rows and the split alone.
    """
    split = HotPartitionSplit.from_dict(target.hot_split)
    if split is None:
        return {"outcome": "skipped", "reason": "empty_hot_split"}
    live = await table_ref.get_delta_table()
    if live is None:
        return {"outcome": "skipped", "reason": "no_delta_table"}
    current = HotPartitionSplit.from_dict(schema.partition_hot_split)
    if not await asyncio.to_thread(stage_hot_partition_split, schema, split=split.to_dict(), claim_token=claim_token):
        raise RepartitionSupersededError(f"hot partition split superseded before staging schema_id={schema.id}")

    present = set(await asyncio.to_thread(measure_partition_bytes, live))
    partitions_split = 0
    rows_rewritten = 0
    for base, count in sorted(split.buckets.items()):
        current_count = current.buckets.get(base) if current else None
        if current_count == count:
            continue
        old_keys = ({base} | _bucket_keys(base, current_count) | _bucket_keys(base, count)) & present
        if not old_keys:
            continue
        if should_stop is not None and should_stop():
            raise RepartitionStoppedError(
                f"hot partition split stopped after {partitions_split} partitions", rows_written=rows_rewritten
            )
        await _ensure_claim(schema, claim_token)
        rows = await asyncio.to_thread(_rewrite_partition, live, base, old_keys, split)
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
