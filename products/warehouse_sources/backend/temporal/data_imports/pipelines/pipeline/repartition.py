"""In-place, streaming repartitioning of a DeltaLake table.

Incremental syncs merge new rows into a Delta table partition-by-partition, but delta-rs reads the
*whole* target partition into worker memory to do it. Once a single partition grows past ~1.5 GB
at-rest it OOMs the worker. The historical fix was a reset + full resync that re-pulls every row from
the source. This module instead repartitions the data **already in S3**, streaming one record-batch
at a time, so it never re-extracts from the source and never materialises an oversized partition.

The rewrite is a pure map (recompute `_ph_partition_key` per row under a finer scheme) into a sibling
temp table, followed by a crash-safe swap. The live table is never mutated until a fully-built temp
table exists, and temp stays the source of truth until the swap is verified — so a worker death at any
point loses at most wasted compute, never data. See the "Repartitioning" section in
`products/warehouse_sources/backend/temporal/data_imports/README.md`.
"""

from __future__ import annotations

import math
import asyncio
import dataclasses
from collections import defaultdict
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import deltalake as deltalake
from structlog.types import FilteringBoundLogger

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_table_helper import (
    _realign_decimal_buffers,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    append_partition_key_to_table,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_table_helper import (
        DeltaTableHelper,
    )

# Coarse → fine. A datetime table that's OOMing steps one tier finer each repartition cycle.
DATETIME_FORMAT_TIERS: list[PartitionFormat] = ["month", "week", "day", "hour"]

# Rows per streamed record-batch. Bounds the repartition's peak memory independent of partition size.
DEFAULT_REPARTITION_BATCH_SIZE = 50_000

TEMP_URI_SUFFIX = "__repartitioned"


class RepartitionUnpartitionableError(Exception):
    """The table has no column suitable for partitioning — repartition is skipped, not retried."""


@dataclasses.dataclass(frozen=True)
class RepartitionTarget:
    """The partition scheme to rewrite a table into. `partition_mode=None` means auto-detect."""

    partition_keys: list[str]
    trigger_reason: str
    partition_mode: PartitionMode | None = None
    partition_format: PartitionFormat | None = None
    partition_count: int | None = None
    partition_size: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepartitionTarget:
        fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in fields})


def measure_partition_bytes(delta_table: deltalake.DeltaTable) -> dict[str | None, int]:
    """At-rest bytes per partition, read from the Delta log (no S3 LIST, no data scan).

    Unpartitioned tables collapse to a single `None` bucket. Keyed by the `_ph_partition_key` value.
    """
    actions = delta_table.get_add_actions(flatten=True)
    columns = actions.schema.names
    sizes = actions.column("size_bytes").to_pylist()

    partition_column = f"partition.{PARTITION_KEY}"
    keys: list[str | None]
    if partition_column in columns:
        keys = list(actions.column(partition_column).to_pylist())
    else:
        keys = [None] * len(sizes)

    totals: dict[str | None, int] = defaultdict(int)
    for key, size in zip(keys, sizes):
        totals[key] += size or 0
    return dict(totals)


def _table_row_count(delta_table: deltalake.DeltaTable) -> int:
    """Total rows from the Delta log's per-file `num_records` (metadata only, no scan)."""
    actions = delta_table.get_add_actions(flatten=True)
    if "num_records" not in actions.schema.names:
        # Fall back to a metadata-only count if the stat is unavailable.
        return delta_table.to_pyarrow_dataset().count_rows()
    return sum(n or 0 for n in actions.column("num_records").to_pylist())


def select_repartition_target(
    schema: ExternalDataSchema,
    partition_bytes: dict[str | None, int],
    target_partition_bytes: int,
) -> tuple[RepartitionTarget | None, str]:
    """Pick the next finer partition scheme, returning (target, reason).

    Computes the target directly from measured bytes so one repartition lands under budget rather
    than stepping blindly: md5 grows the bucket count, numerical shrinks the row-size, datetime steps
    one format tier finer. When no target is chosen the reason explains why (reported in metrics so a
    skipped table is diagnosable): `within_budget`, `datetime_at_finest_tier`, `numerical_cannot_shrink`,
    `numerical_no_size`, or `unpartitionable_no_keys`. A chosen target carries reason `selected`.
    """
    if not partition_bytes:
        return None, "no_partitions"

    max_bytes = max(partition_bytes.values())
    if max_bytes <= target_partition_bytes:
        return None, "within_budget"

    total_bytes = sum(partition_bytes.values())
    mode = schema.partition_mode
    keys = schema.partitioning_keys or schema.primary_key_columns or []

    if mode == "md5":
        current = schema.partition_count or len(partition_bytes) or 1
        new_count = max(current + 1, math.ceil(total_bytes / target_partition_bytes))
        return RepartitionTarget(
            partition_keys=keys, trigger_reason="", partition_mode="md5", partition_count=new_count
        ), "selected"

    if mode == "numerical":
        current_size = schema.partition_size
        if not current_size:
            return None, "numerical_no_size"
        new_size = max(1, math.floor(current_size * target_partition_bytes / max_bytes))
        if new_size >= current_size:
            return None, "numerical_cannot_shrink"
        return RepartitionTarget(
            partition_keys=keys, trigger_reason="", partition_mode="numerical", partition_size=new_size
        ), "selected"

    if mode == "datetime":
        current_format: PartitionFormat = schema.partition_format or "month"
        try:
            next_index = DATETIME_FORMAT_TIERS.index(current_format) + 1
        except ValueError:
            next_index = 1
        if next_index >= len(DATETIME_FORMAT_TIERS):
            # Already at the finest tier (hour) — can't go finer. Caller alerts.
            return None, "datetime_at_finest_tier"
        return RepartitionTarget(
            partition_keys=keys,
            trigger_reason="",
            partition_mode="datetime",
            partition_format=DATETIME_FORMAT_TIERS[next_index],
        ), "selected"

    # Unpartitioned but over budget: attempt to enable partitioning via auto-detection. Needs keys.
    if not keys:
        return None, "unpartitionable_no_keys"
    return RepartitionTarget(partition_keys=keys, trigger_reason="", partition_mode=None), "selected"


def _read_next_batch(reader: pa.RecordBatchReader) -> pa.RecordBatch | None:
    try:
        return reader.read_next_batch()
    except StopIteration:
        return None


async def _rewrite_into_temp(
    *,
    old_delta: deltalake.DeltaTable,
    temp_uri: str,
    storage_options: dict[str, str],
    target: RepartitionTarget,
    batch_size: int,
    logger: FilteringBoundLogger,
) -> tuple[int, RepartitionTarget]:
    """Stream the live table into a fresh temp table under the new partition scheme.

    Returns (rows_written, resolved_target). The first batch resolves any auto-detected mode/format/
    keys so every subsequent batch is bucketed identically (a per-batch auto-detect could disagree).
    """
    dataset = await asyncio.to_thread(old_delta.to_pyarrow_dataset)
    reader = await asyncio.to_thread(lambda: dataset.scanner(batch_size=batch_size).to_reader())

    resolved: RepartitionTarget | None = None
    rows_written = 0

    while True:
        batch = await asyncio.to_thread(_read_next_batch, reader)
        if batch is None:
            break

        table = pa.Table.from_batches([batch])
        if table.num_rows == 0:
            continue
        if PARTITION_KEY in table.column_names:
            table = table.drop([PARTITION_KEY])

        result = append_partition_key_to_table(
            table=table,
            partition_count=target.partition_count,
            partition_size=target.partition_size,
            partition_keys=target.partition_keys,
            partition_mode=resolved.partition_mode if resolved else target.partition_mode,
            partition_format=resolved.partition_format if resolved else target.partition_format,
            logger=logger,
        )
        if result is None:
            raise RepartitionUnpartitionableError(f"No supported partition mode for keys={target.partition_keys}")

        partitioned_table, used_mode, used_format, used_keys = result
        if resolved is None:
            resolved = dataclasses.replace(
                target,
                partition_mode=used_mode,
                partition_format=used_format,
                partition_keys=used_keys,
            )

        partitioned_table = _realign_decimal_buffers(partitioned_table)

        await asyncio.to_thread(
            deltalake.write_deltalake,
            temp_uri,
            partitioned_table,
            partition_by=PARTITION_KEY,
            mode="append",
            schema_mode="merge",
            storage_options=storage_options,
        )
        rows_written += partitioned_table.num_rows

    if resolved is None:
        # Empty source table — nothing to rewrite.
        resolved = target
    return rows_written, resolved


async def repartition_table_in_place(
    helper: DeltaTableHelper,
    schema: ExternalDataSchema,
    target: RepartitionTarget,
    logger: FilteringBoundLogger,
    *,
    batch_size: int = DEFAULT_REPARTITION_BATCH_SIZE,
) -> dict[str, Any]:
    """Rewrite the schema's Delta table under `target`'s finer partition scheme, in place, from S3.

    Memory is bounded by `batch_size`; the source is never re-read. Crash-safe via the
    `repartition_swap` marker (resume re-drives the swap from the intact temp table). On success,
    persists the new partition settings and clears the controller markers. Returns a stats dict for
    observability. Raises `RepartitionUnpartitionableError` (terminal) if no partition mode applies.
    """
    live_uri = await helper.get_table_uri()
    temp_uri = f"{live_uri}{TEMP_URI_SUFFIX}"
    storage_options = helper.get_storage_options()

    # Resume path: a prior attempt already built + validated temp and recorded the swap marker.
    swap = schema.repartition_swap
    resuming = bool(swap and swap.get("state") == "ready")

    old_delta = await helper.get_delta_table()
    if old_delta is None:
        # Live table missing. If a swap was already in progress (temp built + marker recorded), an
        # interrupted prior run may have deleted live *after* recording the marker but before copying
        # temp back. temp is the durable source of truth in that window, so resume the swap from it
        # rather than skipping — a plain skip would strand the markers forever (every later run hits
        # this same early return) and let the next sync bootstrap an empty table over the lost data.
        if resuming:
            return await _resume_swap_with_missing_live(
                helper=helper,
                schema=schema,
                target=target,
                temp_uri=temp_uri,
                live_uri=live_uri,
                storage_options=storage_options,
                logger=logger,
            )
        await logger.ainfo(f"repartition: no delta table, skipping schema_id={schema.id}", schema_id=str(schema.id))
        return {"outcome": "skipped", "reason": "no_delta_table"}

    partition_bytes = await asyncio.to_thread(measure_partition_bytes, old_delta)
    max_partition_bytes_before = max(partition_bytes.values()) if partition_bytes else 0
    total_table_bytes = sum(partition_bytes.values())
    old_row_count = await asyncio.to_thread(_table_row_count, old_delta)

    before = {
        "partition_mode": schema.partition_mode,
        "partition_format": schema.partition_format,
        "partition_count": schema.partition_count,
        "partition_size": schema.partition_size,
    }

    if resuming:
        resolved = target
        # `rows_written` is set from the swap's temp-derived count below; `old_row_count` here was read
        # from a live table a prior partial swap may have inflated, so it isn't trustworthy.
        rows_written = 0
        await logger.ainfo(f"repartition: resuming from swap marker schema_id={schema.id}", schema_id=str(schema.id))
    else:
        # Fresh build: clear any stale temp folder, then stream the live table into it.
        async with aget_s3_client() as s3:
            if await s3._exists(temp_uri):
                await s3._rm(temp_uri, recursive=True)

        rows_written, resolved = await _rewrite_into_temp(
            old_delta=old_delta,
            temp_uri=temp_uri,
            storage_options=storage_options,
            target=target,
            batch_size=batch_size,
            logger=logger,
        )

        # Validate before any destructive action — temp must hold every row.
        new_delta = await asyncio.to_thread(deltalake.DeltaTable, table_uri=temp_uri, storage_options=storage_options)
        new_row_count = await asyncio.to_thread(_table_row_count, new_delta)
        if new_row_count != old_row_count:
            raise ValueError(
                f"repartition row-count mismatch: temp={new_row_count} live={old_row_count} "
                f"(schema_id={schema.id}) — refusing to swap"
            )

        # Marker makes the swap idempotent: temp stays the source of truth until it's confirmed live.
        await asyncio.to_thread(
            schema.set_repartition_swap, {"state": "ready", "temp_uri": temp_uri, "live_uri": live_uri}
        )

    # Swap (idempotent): replace live with a server-side copy of temp, verify, then drop temp. temp
    # holds the full re-bucketed dataset, so deleting live is safe — temp is the new source of truth.
    # The swap verifies against temp's own count, so a resume over an inflated live recovers cleanly.
    swapped_rows = await _swap_temp_into_live(
        temp_uri=temp_uri,
        live_uri=live_uri,
        storage_options=storage_options,
    )
    if resuming:
        # On resume `old_row_count` was read from a possibly-inflated live table; temp is the truth.
        rows_written = swapped_rows

    # Persist the new scheme and clear controller state. set_partitioning_enabled saves + pops overrides.
    await asyncio.to_thread(
        schema.set_partitioning_enabled,
        resolved.partition_keys,
        resolved.partition_count,
        resolved.partition_size,
        resolved.partition_mode,
        resolved.partition_format,
    )
    await asyncio.to_thread(schema.clear_repartition_swap)
    await asyncio.to_thread(schema.clear_repartition_pending)
    await asyncio.to_thread(schema.stamp_last_repartition_at)

    # The cached delta-table object points at the pre-swap files; drop it so callers re-read live.
    helper.get_delta_table.cache_clear()

    await logger.ainfo(
        f"repartition: completed schema_id={schema.id} rows={rows_written} "
        f"mode={before['partition_mode']}->{resolved.partition_mode} "
        f"format={before['partition_format']}->{resolved.partition_format} "
        f"count={before['partition_count']}->{resolved.partition_count} "
        f"size={before['partition_size']}->{resolved.partition_size}",
        schema_id=str(schema.id),
        rows=rows_written,
        mode=f"{before['partition_mode']}->{resolved.partition_mode}",
        format=f"{before['partition_format']}->{resolved.partition_format}",
        count=f"{before['partition_count']}->{resolved.partition_count}",
        size=f"{before['partition_size']}->{resolved.partition_size}",
    )

    return {
        "outcome": "completed",
        "row_count": rows_written,
        "max_partition_bytes_before": max_partition_bytes_before,
        "total_table_bytes": total_table_bytes,
        "partition_mode_before": before["partition_mode"],
        "partition_mode_after": resolved.partition_mode,
        "partition_format_before": before["partition_format"],
        "partition_format_after": resolved.partition_format,
        "partition_count_before": before["partition_count"],
        "partition_count_after": resolved.partition_count,
        "partition_size_before": before["partition_size"],
        "partition_size_after": resolved.partition_size,
    }


async def _resume_swap_with_missing_live(
    *,
    helper: DeltaTableHelper,
    schema: ExternalDataSchema,
    target: RepartitionTarget,
    temp_uri: str,
    live_uri: str,
    storage_options: dict[str, str],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    """Finish a swap whose live table was already deleted by an interrupted prior run.

    Entered only when the swap marker is set but live is gone — i.e. a previous run crashed inside
    `_swap_temp_into_live` after deleting live and before the copy completed. temp is the durable
    source of truth, so its own row count is the swap's expectation. If temp is *also* gone there is
    nothing left to recover (both folders lost): clear the markers and skip so the next sync rebuilds.
    """
    async with aget_s3_client() as s3:
        temp_present = await s3._exists(temp_uri)
    if not temp_present:
        await asyncio.to_thread(schema.clear_repartition_swap)
        await asyncio.to_thread(schema.clear_repartition_pending)
        await logger.ainfo(
            f"repartition: live and temp both missing, skipping schema_id={schema.id}", schema_id=str(schema.id)
        )
        return {"outcome": "skipped", "reason": "no_delta_table"}

    await logger.ainfo(
        f"repartition: live missing mid-swap, resuming from temp schema_id={schema.id}", schema_id=str(schema.id)
    )
    expected_rows = await _swap_temp_into_live(
        temp_uri=temp_uri,
        live_uri=live_uri,
        storage_options=storage_options,
    )

    await asyncio.to_thread(
        schema.set_partitioning_enabled,
        target.partition_keys,
        target.partition_count,
        target.partition_size,
        target.partition_mode,
        target.partition_format,
    )
    await asyncio.to_thread(schema.clear_repartition_swap)
    await asyncio.to_thread(schema.clear_repartition_pending)
    await asyncio.to_thread(schema.stamp_last_repartition_at)
    helper.get_delta_table.cache_clear()

    await logger.ainfo(
        f"repartition: recovered from interrupted swap schema_id={schema.id} rows={expected_rows}",
        schema_id=str(schema.id),
        rows=expected_rows,
    )
    return {"outcome": "completed", "row_count": expected_rows, "recovered": True}


async def _clear_prefix(s3: Any, uri: str) -> None:
    """Delete every object under `uri`, robust to eventually-consistent S3-compatible stores.

    A single recursive prefix delete can leave directory-marker objects (and, under eventual
    consistency, stray data files) behind on some S3-compatible stores. List the files and delete
    them explicitly first, then a best-effort recursive sweep to catch any markers.
    """
    if not await s3._exists(uri):
        return
    files = await s3._find(uri)
    if files:
        await s3._rm([f"s3://{f.lstrip('/')}" for f in files])
    if await s3._exists(uri):
        await s3._rm(uri, recursive=True)


async def _swap_temp_into_live(
    *,
    temp_uri: str,
    live_uri: str,
    storage_options: dict[str, str],
) -> int:
    """Atomically-enough replace `live_uri` with the contents of `temp_uri`. Returns temp's row count.

    Crash-safe ordering: delete live → server-side copy temp → live → verify → delete temp. Until
    temp is deleted it remains the durable source of truth, so any retry simply re-runs this whole
    function (Delta uses relative paths in `_delta_log`, so a copied folder is a valid table).

    The verification target is temp's *own* row count, never a pre-swap live count. A prior partial
    swap can leave live inflated (leftover files under the live prefix make the new Delta log
    reference duplicate records), and re-deriving the expectation from that inflated live would both
    accept a corrupt table and permanently fail an otherwise-clean retry. temp is the durable source
    of truth, so its count is the expectation — matching `_resume_swap_with_missing_live`.

    Files are copied one at a time preserving their path relative to temp — a single recursive
    `copy(prefix, prefix)` trips over directory-marker objects on S3-compatible stores.
    """
    temp_prefix = temp_uri.replace("s3://", "").rstrip("/")
    temp_delta = await asyncio.to_thread(deltalake.DeltaTable, table_uri=temp_uri, storage_options=storage_options)
    expected_rows = await asyncio.to_thread(_table_row_count, temp_delta)

    async with aget_s3_client() as s3:
        if await s3._exists(temp_uri):
            # Fully clear the live prefix before copying temp in. Any leftover old data file would
            # make the new Delta log reference duplicate records (the ~2x inflation we're guarding
            # against), so this must be an explicit file-list delete, not just a recursive sweep.
            await _clear_prefix(s3, live_uri)
            files = await s3._find(temp_uri)
            for f in files:
                rel = f[len(temp_prefix) :]
                await s3._copy(f"s3://{f.lstrip('/')}", f"{live_uri}{rel}")

    # Verify the live copy is a valid Delta table with the expected row count before dropping temp.
    live_delta = await asyncio.to_thread(deltalake.DeltaTable, table_uri=live_uri, storage_options=storage_options)
    live_rows = await asyncio.to_thread(_table_row_count, live_delta)
    if live_rows != expected_rows:
        # The pre-swap live files are already gone, so there is nothing to roll back to. Clear the
        # corrupt (partially-copied / inflated) live so it fails loud (missing table) instead of
        # silently serving wrong rows. temp and the swap marker stay intact, so the next run recovers
        # cleanly via `_resume_swap_with_missing_live`.
        async with aget_s3_client() as s3:
            await _clear_prefix(s3, live_uri)
        raise ValueError(f"repartition swap verification failed: live={live_rows} expected={expected_rows}")

    async with aget_s3_client() as s3:
        await _clear_prefix(s3, temp_uri)

    return expected_rows
