"""SCD Type 2 history written once per sync: `stage` appends each batch, `finalize` writes the sync.

A history write per batch rewrites every `current` file that holds a changed key, so its cost grows
with the table on every batch. Here each batch only appends to a staging table. `finalize` hands the
staged rows to deltalite's `history_upsert`, which opens new versions, closes the versions they
replace, and commits both in one Delta commit.

`history_upsert` drops every row that is not newer than its key's open version, so a call with input
it already applied changes nothing. A crash after a commit and before the staging cleanup is
therefore harmless: the re-run applies nothing twice.
"""

import math
import time
import asyncio
import tempfile
import functools
import contextlib
import dataclasses
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings

import numpy as np
import pyarrow as pa
import deltalake
import pyarrow.compute as pc
import pyarrow.dataset as ds

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    CURRENT_HISTORY_PARTITION,
    HistoryNaming,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    align_incoming_decimals_to_delta,
    normalize_column_name,
    pyarrow_schema_from_arrow_exportable,
    realign_decimal_buffers,
    relax_batch_nullability,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.evolution import evolve_delta_schema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import VACUUM_RETENTION
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.memory_governor import get_governor
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    DELTA_TABLE_PROPERTIES,
    ensure_table_properties,
    execute_with_conflict_retry,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import (
    DeltaWriter,
    _deltalite_write_stats,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef

STAGED_BATCH_COLUMN = "_ph_staged_batch"
# Append order, `staging version << 32 | row`. It decides which of two rows with the same key and order value
# wins, also between runs whose staged rows are finalized together, because the staging version only grows.
STAGED_ROW_COLUMN = "_ph_staged_row"
_STAGING_COLUMNS = (STAGED_BATCH_COLUMN, STAGED_ROW_COLUMN)
# deltalite refuses a source above 2 GiB, counted with its key map. The staged size is an estimate, so
# one call takes at most half of that.
MAX_CALL_BYTES = 1024 * 1024 * 1024
# Each chunk rewrites the `current` files that hold its keys, so chunks stay as large as memory allows.
CHUNK_TARGET_BYTES = 512 * 1024 * 1024
# Rows per scanned batch, so one decoded batch of wide rows stays small next to the call budget.
_SCAN_BATCH_ROWS = 16_384
# Each chunk holds one open spill file while the staging table is read. Past this many chunks, a chunk grows
# instead.
_MAX_CHUNKS = 256
# deltalite's source guard also counts its copies of the key, order and tie-break columns (about twice their
# size) and a key-map entry plus two row indexes per row.
_INDEX_BYTES_PER_ROW = 48 + 2 * 4
_SUMMED_STATS = (
    "rows_in",
    "rows_deduped",
    "rows_reread",
    "rows_backwards",
    "versions_opened",
    "versions_closed",
    "chain_rows_closed",
    "files_removed",
    "files_added",
    "bytes_read",
    "bytes_written",
)


@frozen
class HistoryFinalizeResult:
    staged_rows: int
    calls: int
    rows_in: int = 0
    rows_deduped: int = 0
    rows_reread: int = 0
    rows_backwards: int = 0
    versions_opened: int = 0
    versions_closed: int = 0
    chain_rows_closed: int = 0
    files_removed: int = 0
    files_added: int = 0
    bytes_read: int = 0
    bytes_written: int = 0


async def stage(
    staging: "DeltaTableRef",
    data: pa.Table,
    *,
    key_columns: Sequence[str],
    naming: HistoryNaming,
    run_uuid: str,
    batch_index: int,
) -> None:
    """Stage one batch. Each row needs the key columns and `valid_from`, which also orders a key's versions.

    The commit carries the batch's `run_uuid` and `batch_index`, so the load path's redelivery
    check finds it on the staging table. A batch staged twice still makes one version per row.
    """
    if data.num_rows == 0:
        return
    key_columns = _normalized_keys(key_columns)
    data = relax_batch_nullability(realign_decimal_buffers(data))
    missing = [c for c in (*key_columns, naming.valid_from) if c not in data.column_names]
    if missing:
        raise ValueError(f"History batch is missing column(s) {missing}")
    taken = [c for c in _STAGING_COLUMNS if c in data.column_names]
    if taken:
        raise ValueError(f"History batch has column(s) {taken}, which the staging table writes itself")
    data = data.drop_columns([c for c in (naming.valid_to, naming.partition_column) if c in data.column_names])
    staging_table = await staging.get_delta_table()
    # Creating the table commits version 0, so the first append is version 1.
    first_row = (staging_table.version() + 1 if staging_table is not None else 1) << 32
    data = data.append_column(
        STAGED_BATCH_COLUMN, pa.repeat(pa.scalar(f"{run_uuid}:{batch_index}"), data.num_rows)
    ).append_column(STAGED_ROW_COLUMN, pa.array(np.arange(first_row, first_row + data.num_rows, dtype=np.int64)))

    if staging_table is None:
        staging_table = await asyncio.to_thread(
            deltalake.DeltaTable.create,
            table_uri=await staging.get_table_uri(),
            schema=data.schema,
            storage_options=staging.get_storage_options(),
            configuration=DELTA_TABLE_PROPERTIES,
        )
        staging.adopt_created_table(staging_table)
    else:
        # A new column joins as nullable, because the rows staged before it do not have it.
        staging_table = await evolve_delta_schema(staging_table, data.schema)
        data = align_incoming_decimals_to_delta(data, staging_table.schema())
    await asyncio.to_thread(
        deltalake.write_deltalake,
        table_or_uri=staging_table,
        data=data,
        mode="append",
        schema_mode="merge",
        commit_properties=deltalake.CommitProperties(
            custom_metadata={"run_uuid": run_uuid, "batch_index": str(batch_index)}
        ),
    )


async def finalize(
    table: "DeltaTableRef",
    staging: "DeltaTableRef",
    *,
    key_columns: Sequence[str],
    naming: HistoryNaming,
    commit_metadata: dict[str, str] | None = None,
    max_call_bytes: int = MAX_CALL_BYTES,
    chunk_target_bytes: int = CHUNK_TARGET_BYTES,
) -> HistoryFinalizeResult | None:
    """Write every staged row into the history table, then delete the staged rows. None when nothing is staged.

    Staged rows that fit one call go in one commit. Larger syncs split by a hash of the key, one commit
    per chunk. Chunks hold disjoint keys, so a crash between two chunk commits leaves each key either
    fully applied or not at all, and the re-run applies only the rest. Only the last call carries
    `commit_metadata`, so a tagged commit means the whole sync is in the table.
    """
    key_columns = _normalized_keys(key_columns)
    partition_column = naming.partition_column
    if partition_column is None:
        raise ValueError(f"{table.resource_name} has no history partition column, which a history upsert needs")
    staging_table = await staging.get_delta_table()
    if staging_table is None:
        return None
    add_actions = pa.table(staging_table.get_add_actions(flatten=True))
    if add_actions.num_rows == 0 or pc.sum(add_actions["num_records"]).as_py() == 0:
        return None

    staged_schema = pyarrow_schema_from_arrow_exportable(staging_table.schema())
    history_table = await _history_table(table, staged_schema, naming, partition_column)
    staging_dataset = staging_table.to_pyarrow_dataset()
    # The batch tags are only needed for the cleanup, so they never reach the upsert.
    columns = [name for name in staging_dataset.schema.names if name != STAGED_BATCH_COLUMN]
    batch_tags = await asyncio.to_thread(_batch_tags, staging_dataset)
    narrow_columns = list(dict.fromkeys([*key_columns, naming.valid_from, STAGED_ROW_COLUMN]))
    call_bytes = await asyncio.to_thread(_call_bytes, staging_dataset, columns, narrow_columns)
    # One handle for every chunk, so each call does not load the table's log and checkpoint again.
    handle = await asyncio.to_thread(_open_deltalite, await table.get_table_uri(), table.get_storage_options())

    totals = dict.fromkeys(_SUMMED_STATS, 0)
    calls = staged_rows = 0
    with tempfile.TemporaryDirectory(prefix="history-finalize-") as directory:
        sources: list[tuple[Callable[[], pa.Table], int]]
        if call_bytes <= max_call_bytes:
            sources = [(functools.partial(_read_staged, staging_dataset, columns), call_bytes)]
        else:
            chunks = min(_MAX_CHUNKS, math.ceil(call_bytes / chunk_target_bytes))
            spilled = await asyncio.to_thread(
                _spill_chunks, handle, staging_dataset, columns, key_columns, narrow_columns, chunks, Path(directory)
            )
            sources = [(functools.partial(_read_chunk, path), footprint) for path, footprint in spilled]
        for index, (load, footprint) in enumerate(sources):
            if calls:
                # The earlier chunk's commit made the handle stale, and the new columns must align to the table.
                history_table = await table.get_delta_table() or history_table
            stats, rows = await _history_upsert(
                table,
                handle,
                history_table,
                load,
                footprint,
                key_columns=key_columns,
                naming=naming,
                partition_column=partition_column,
                commit_metadata=commit_metadata if index == len(sources) - 1 else None,
                chunk=index,
                chunks=len(sources),
            )
            staged_rows += rows
            calls += 1
            for name in _SUMMED_STATS:
                totals[name] += int(getattr(stats, name, 0) or 0)

    # Only after every chunk committed: a crash before this point leaves the rows staged for the re-run.
    await DeltaWriter(staging).delete_where(STAGED_BATCH_COLUMN, batch_tags)
    await _vacuum_staging(staging)
    refreshed = await table.get_delta_table()
    if refreshed is not None:
        await ensure_table_properties(refreshed, table.logger)
    result = HistoryFinalizeResult(staged_rows=staged_rows, calls=calls, **totals)
    await table.logger.ainfo("history_finalize", call_bytes=call_bytes, **dataclasses.asdict(result))
    return result


async def _history_table(
    table: "DeltaTableRef", staged_schema: pa.Schema, naming: HistoryNaming, partition_column: str
) -> deltalake.DeltaTable:
    """The history table, created or evolved to the staged columns plus `valid_to` and the partition column."""
    fields = [field for field in staged_schema if field.name not in _STAGING_COLUMNS]
    valid_from_type = staged_schema.field(naming.valid_from).type
    schema = pa.schema([*fields, pa.field(naming.valid_to, valid_from_type), pa.field(partition_column, pa.string())])
    history_table = await table.get_delta_table()
    if history_table is None:
        history_table = await asyncio.to_thread(
            deltalake.DeltaTable.create,
            table_uri=await table.get_table_uri(),
            schema=schema,
            mode="ignore",
            partition_by=[partition_column],
            storage_options=table.get_storage_options(),
            configuration=DELTA_TABLE_PROPERTIES,
        )
        table.adopt_created_table(history_table)
        return history_table
    return await evolve_delta_schema(history_table, schema)


def _call_bytes(dataset: ds.Dataset, columns: list[str], narrow_columns: list[str]) -> int:
    """What one call with every staged row counts against deltalite's source guard, one batch in memory at a time.

    Parquet stores repeated and null values in a few bytes, so only decoded batches give that size.
    """
    return sum(_footprint(batch, narrow_columns) for batch in _scanner(dataset, columns).to_batches())


def _footprint(batch: pa.RecordBatch, narrow_columns: list[str]) -> int:
    narrow = sum(batch.column(name).nbytes for name in narrow_columns)
    return batch.nbytes + 2 * narrow + batch.num_rows * _INDEX_BYTES_PER_ROW


def _read_staged(dataset: ds.Dataset, columns: list[str]) -> pa.Table:
    return _scanner(dataset, columns).to_table()


def _open_deltalite(uri: str, storage_options: dict[str, str]) -> Any:
    import deltalite  # noqa: PLC0415 - keeps deltalite off the import path of processes that never write with it

    return deltalite.DeltaLiteTable.open(uri, storage_options)


def _spill_chunks(
    handle: Any,
    dataset: ds.Dataset,
    columns: list[str],
    key_columns: Sequence[str],
    narrow_columns: list[str],
    chunks: int,
    directory: Path,
) -> list[tuple[Path, int]]:
    """Write the staged rows into one local Arrow file per key bucket, one record batch at a time.

    The history table hashes the keys after it casts them to its own key types, so two staged values that
    become one table key land in the same bucket. Returns the files that received rows, in bucket order,
    each with its call footprint.
    """
    paths = [directory / f"chunk-{index}.arrow" for index in range(chunks)]
    footprints = [0] * chunks
    schema = pa.schema([dataset.schema.field(name) for name in columns])
    # The chunks together hold the whole staged sync on local disk.
    options = pa.ipc.IpcWriteOptions(compression="zstd")
    with contextlib.ExitStack() as stack:
        writers = [stack.enter_context(pa.ipc.new_file(str(path), schema, options=options)) for path in paths]
        for batch in _scanner(dataset, columns).to_batches():
            if batch.num_rows == 0:
                continue
            buckets = handle.key_buckets(batch, list(key_columns), chunks)
            # One sort per batch, then a slice per bucket, instead of a filter pass per bucket.
            order = pc.sort_indices(buckets)
            sorted_batch = batch.take(order)
            starts = np.searchsorted(buckets.take(order).to_numpy(), np.arange(chunks + 1))
            for index, writer in enumerate(writers):
                count = int(starts[index + 1] - starts[index])
                if count:
                    bucket = sorted_batch.slice(int(starts[index]), count)
                    writer.write_batch(bucket)
                    footprints[index] += _footprint(bucket, narrow_columns)
    return [(path, footprint) for path, footprint in zip(paths, footprints) if footprint]


def _read_chunk(path: Path) -> pa.Table:
    with pa.OSFile(str(path), "rb") as source:
        return pa.ipc.open_file(source).read_all()


def _batch_tags(dataset: ds.Dataset) -> set[str]:
    tags: set[str] = set()
    for batch in _scanner(dataset, [STAGED_BATCH_COLUMN]).to_batches():
        tags.update(str(tag) for tag in pc.unique(batch.column(STAGED_BATCH_COLUMN)).drop_null().to_pylist())
    return tags


def _scanner(dataset: ds.Dataset, columns: list[str]) -> ds.Scanner:
    return dataset.scanner(
        columns=columns, batch_size=_SCAN_BATCH_ROWS, batch_readahead=1, fragment_readahead=1, use_threads=False
    )


def _normalized_keys(key_columns: Sequence[str]) -> list[str]:
    if not key_columns:
        raise ValueError("A history table needs a primary key")
    return [normalize_column_name(key) for key in key_columns]


async def _history_upsert(
    table: "DeltaTableRef",
    handle: Any,
    history_table: deltalake.DeltaTable,
    load: Callable[[], pa.Table],
    footprint: int,
    *,
    key_columns: Sequence[str],
    naming: HistoryNaming,
    partition_column: str,
    commit_metadata: dict[str, str] | None,
    chunk: int,
    chunks: int,
) -> tuple[Any, int]:
    """Read one call's rows inside its governor admission and write them. Returns the stats and the row count."""
    max_row_group_bytes = settings.DATA_WAREHOUSE_DELTALITE_MAX_ROW_GROUP_BYTES
    # The rows are read only once admitted, so a finalize that waits for room holds none of them. That leaves
    # no rows to size a rewrite profile from, and the governor plans for an unknown shape, which errs smaller.
    # deltalite rewrites `current` with one worker and streams the closed versions to month files next to it,
    # whatever plan the governor picks. Those writers hold at most the closed rows, about one per source row,
    # so they count with the source.
    async with get_governor().admit(source_bytes=2 * footprint, n_partitions=1) as adm:
        data = align_incoming_decimals_to_delta(await asyncio.to_thread(load), history_table.schema())

        def _upsert() -> Any:
            return handle.history_upsert(
                data,
                list(key_columns),
                naming.valid_from,
                naming.valid_from,
                naming.valid_to,
                partition_column,
                CURRENT_HISTORY_PARTITION,
                STAGED_ROW_COLUMN,
                commit_metadata=commit_metadata,
                max_row_group_bytes=max_row_group_bytes if max_row_group_bytes > 0 else None,
                **adm.upsert_kwargs,
            )

        started = time.perf_counter()
        stats = await asyncio.to_thread(_upsert)
        duration_s = time.perf_counter() - started
        rows = data.num_rows

    table.note_deltalite_commit(getattr(stats, "version", None))
    with contextlib.suppress(Exception):
        await table.logger.ainfo(
            "history upsert: committed",
            chunk=chunk,
            chunks=chunks,
            duration_ms=round(duration_s * 1000),
            governor_mode=adm.mode,
            governor_predicted_peak_mb=adm.predicted_peak_mb,
            governor_budget_mb=adm.budget_mb,
            governor_capacity_exceeded=adm.capacity_exceeded,
            governor_wait_ms=adm.wait_ms,
            governor_peak_rss_mb=adm.rss.peak_mb if adm.rss else None,
            **_deltalite_write_stats(stats),
        )
    return stats, rows


async def _vacuum_staging(staging: "DeltaTableRef") -> None:
    # The delete only tombstones the staged rows. The files go once they are past the retention every
    # vacuum of this product keeps, so the staging table does not grow with every run.
    staged = await staging.get_delta_table()
    if staged is None:
        return
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
