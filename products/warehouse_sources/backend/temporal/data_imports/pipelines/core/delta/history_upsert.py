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
import shutil
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
# Append order, `staging version << 32 | row`: breaks ties on key and order value, across runs too.
STAGED_ROW_COLUMN = "_ph_staged_row"
_STAGING_COLUMNS = (STAGED_BATCH_COLUMN, STAGED_ROW_COLUMN)
# deltalite refuses a source above this, counted with its key map.
_SOURCE_GUARD_BYTES = 2 * 1024 * 1024 * 1024
# The staged size is an estimate, so one call takes at most half of deltalite's source guard.
MAX_CALL_BYTES = _SOURCE_GUARD_BYTES // 2
# Each chunk rewrites the `current` files that hold its keys, so chunks stay as large as memory allows.
CHUNK_TARGET_BYTES = 512 * 1024 * 1024
# Rows per scanned batch, so one decoded batch of wide rows stays small next to the call budget.
_SCAN_BATCH_ROWS = 16_384
_MAX_OPEN_CHUNK_FILES = 256
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


class HistoryChunkTooLargeError(ValueError):
    """One key chunk of a sync is above deltalite's source limit or half the free local disk.

    Chunks split keys, not a key's versions, so only a key with too many versions causes it.
    """


class _SpillOutOfDisk(Exception):
    """A spill pass brought the free local disk below its floor."""


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
    staging_table = await staging.get_delta_table()
    if data.num_rows == 0 and staging_table is not None:
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
        # An empty first batch still leaves a staging table, which the load path reads the schema from.
        if data.num_rows == 0:
            return
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
    `commit_metadata`, so a tagged commit means the whole sync is in the table. A last call that keeps no
    row makes no commit, so its tag is missing although the sync is applied.

    Chunks spill to local disk in passes. Each pass reads the staging table again and stops at half the disk
    that was free when it started, then runs again with half the chunks, so a large sync needs more reads,
    not more disk.
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
    narrow_columns = list(dict.fromkeys([*key_columns, naming.valid_from, STAGED_ROW_COLUMN]))
    call_bytes, batch_tags = await asyncio.to_thread(_measure, staging_dataset, columns, narrow_columns)
    # One handle for every chunk, so each call does not load the table's log and checkpoint again.
    handle = await asyncio.to_thread(_open_deltalite, await table.get_table_uri(), table.get_storage_options())

    totals = dict.fromkeys(_SUMMED_STATS, 0)
    calls = staged_rows = 0

    async def _apply(load: Callable[[], pa.Table], footprint: int, chunks: int, *, last: bool) -> None:
        nonlocal calls, staged_rows
        stats, rows = await _history_upsert(
            table,
            handle,
            history_table,
            load,
            footprint,
            key_columns=key_columns,
            naming=naming,
            partition_column=partition_column,
            commit_metadata=commit_metadata if last else None,
            chunk=calls,
            chunks=chunks,
        )
        staged_rows += rows
        calls += 1
        for name in _SUMMED_STATS:
            totals[name] += int(getattr(stats, name))

    with tempfile.TemporaryDirectory(prefix="history-finalize-") as directory:
        if call_bytes <= max_call_bytes:
            await _apply(functools.partial(_read_staged, staging_dataset, columns), call_bytes, 1, last=True)
        else:
            chunks = math.ceil(call_bytes / chunk_target_bytes)
            spill_directory = Path(directory)
            per_pass = max(1, min(_MAX_OPEN_CHUNK_FILES, _free_bytes(spill_directory) // 2 // chunk_target_bytes))
            first = 0
            while first < chunks:
                buckets = range(first, min(chunks, first + per_pass))
                # A chunk can be far above the target, and other spills share the disk, so the pass watches
                # the free disk itself and stops at half of what was free when it started.
                floor = _free_bytes(spill_directory) // 2
                try:
                    spilled = await asyncio.to_thread(
                        _spill_chunks,
                        handle,
                        history_table.schema(),
                        staging_dataset,
                        columns,
                        key_columns,
                        narrow_columns,
                        chunks,
                        buckets,
                        spill_directory,
                        floor,
                    )
                except _SpillOutOfDisk:
                    for path in spill_directory.iterdir():
                        path.unlink()
                    if len(buckets) == 1:
                        raise HistoryChunkTooLargeError(
                            f"{table.resource_name}: a key chunk of this sync needs more than half the free "
                            f"local disk ({floor} bytes)"
                        )
                    per_pass = len(buckets) // 2
                    continue
                for index, (path, footprint) in enumerate(spilled):
                    last = buckets.stop == chunks and index == len(spilled) - 1
                    await _apply(functools.partial(_read_chunk, path), footprint, chunks, last=last)
                    path.unlink()
                first = buckets.stop

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


def _measure(dataset: ds.Dataset, columns: list[str], narrow_columns: list[str]) -> tuple[int, set[str]]:
    """What one call with every staged row counts against deltalite's source guard, and the staged batch tags.

    One batch is in memory at a time. Parquet stores repeated and null values in a few bytes, so only
    decoded batches give that size.
    """
    footprint = 0
    tags: set[str] = set()
    for batch in _scanner(dataset, [*columns, STAGED_BATCH_COLUMN]).to_batches():
        tag_column = batch.column(STAGED_BATCH_COLUMN)
        tags.update(str(tag) for tag in pc.unique(tag_column).drop_null().to_pylist())
        footprint += _footprint(batch, narrow_columns) - tag_column.nbytes
    return footprint, tags


def _free_bytes(directory: Path) -> int:
    return shutil.disk_usage(directory).free


def _footprint(batch: pa.RecordBatch, narrow_columns: list[str]) -> int:
    narrow = sum(batch.column(name).nbytes for name in narrow_columns)
    return batch.nbytes + 2 * narrow + batch.num_rows * _INDEX_BYTES_PER_ROW


def _read_staged(dataset: ds.Dataset, columns: list[str]) -> pa.Table:
    # The scanner's batches are slices that share their row group's decoded buffers, and deltalite's source guard
    # counts the whole buffer once per slice. A large staged batch then counts many times its size and is refused.
    # One contiguous copy is counted at its real size, and it stays under MAX_CALL_BYTES, so string offsets fit.
    return _scanner(dataset, columns).to_table().combine_chunks()


def _open_deltalite(uri: str, storage_options: dict[str, str]) -> Any:
    import deltalite  # noqa: PLC0415 - keeps deltalite off the import path of processes that never write with it

    return deltalite.DeltaLiteTable.open(uri, storage_options)


def _spill_chunks(
    handle: Any,
    history_schema: Any,
    dataset: ds.Dataset,
    columns: list[str],
    key_columns: Sequence[str],
    narrow_columns: list[str],
    chunks: int,
    buckets: range,
    directory: Path,
    free_floor: int,
) -> list[tuple[Path, int]]:
    """Write the staged rows of the key buckets in `buckets` into one local Arrow file per bucket.

    The rows are aligned to the history table's decimal types first, so the history table hashes the keys
    the upsert matches. It hashes them after it casts them to its own key types, so two staged values that
    become one table key land in the same bucket. Returns the files that received rows, in bucket order,
    each with its call footprint. Stops once the free disk drops below `free_floor`, or a bucket's
    footprint passes deltalite's source limit.
    """
    paths = {bucket: directory / f"chunk-{bucket}.arrow" for bucket in buckets}
    footprints = dict.fromkeys(buckets, 0)
    staged_schema = pa.schema([dataset.schema.field(name) for name in columns])
    schema = align_incoming_decimals_to_delta(staged_schema.empty_table(), history_schema).schema
    options = pa.ipc.IpcWriteOptions(compression="zstd")
    with contextlib.ExitStack() as stack:
        writers = {
            bucket: stack.enter_context(pa.ipc.new_file(str(path), schema, options=options))
            for bucket, path in paths.items()
        }
        for staged in _scanner(dataset, columns).to_batches():
            if staged.num_rows == 0:
                continue
            aligned = align_incoming_decimals_to_delta(pa.Table.from_batches([staged]), history_schema)
            for batch in aligned.to_batches():
                ids = handle.key_buckets(batch, list(key_columns), chunks)
                order = pc.sort_indices(ids)
                sorted_batch = batch.take(order)
                starts = np.searchsorted(ids.take(order).to_numpy(), np.arange(chunks + 1))
                for bucket, writer in writers.items():
                    count = int(starts[bucket + 1] - starts[bucket])
                    if count:
                        rows = sorted_batch.slice(int(starts[bucket]), count)
                        writer.write_batch(rows)
                        footprints[bucket] += _footprint(rows, narrow_columns)
                        if footprints[bucket] > _SOURCE_GUARD_BYTES:
                            raise HistoryChunkTooLargeError(
                                f"A key chunk of this sync holds over deltalite's {_SOURCE_GUARD_BYTES} byte "
                                "source limit, so one key has too many versions"
                            )
            if _free_bytes(directory) < free_floor:
                raise _SpillOutOfDisk()
    return [(paths[bucket], footprints[bucket]) for bucket in buckets if footprints[bucket]]


def _read_chunk(path: Path) -> pa.Table:
    with pa.OSFile(str(path), "rb") as source:
        return pa.ipc.open_file(source).read_all()


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
    # Rows are read only once admitted, so a finalize waiting for room holds none. The closed versions
    # deltalite writes are at most one per source row, so they count with the source.
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

    committed = bool(stats.committed)
    if committed:
        table.note_deltalite_commit(stats.version)
    with contextlib.suppress(Exception):
        await table.logger.ainfo(
            "history upsert: committed" if committed else "history upsert: nothing to write",
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
    # The delete only tombstones the rows. Vacuum drops their files past retention, so staging doesn't grow.
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
