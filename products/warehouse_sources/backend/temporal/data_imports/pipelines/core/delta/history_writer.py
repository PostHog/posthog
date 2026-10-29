import json
import asyncio
import tempfile
import dataclasses
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import duckdb
import pyarrow as pa
import deltalake
import pyarrow.compute as pc
import pyarrow.dataset as ds

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    align_incoming_decimals_to_delta,
    normalize_column_name,
    pyarrow_schema_from_arrow_exportable,
    realign_decimal_buffers,
    relax_batch_nullability,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.evolution import evolve_delta_schema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    DELTA_TABLE_PROPERTIES,
    delta_merge_spill_kwargs,
    ensure_table_properties,
    execute_with_conflict_retry,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import live_size_mib
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import (
    DeltaWriter,
    _merge_predicate_ops,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef

STAGED_BATCH_COLUMN = "_ph_staged_batch"
# Append order, `staging version << 32 | row`. It decides which of two rows with the same key and order value
# wins, also across runs, because the staging version only grows.
STAGED_ROW_COLUMN = "_ph_staged_row"
_STAGING_COLUMNS = (STAGED_BATCH_COLUMN, STAGED_ROW_COLUMN)
# Compressed staged bytes per bucket. Parquet expands several times in memory, so a bucket stays a few hundred MB.
DEFAULT_BUCKET_TARGET_MIB = 32
# Each bucket holds one open spill file while the staging table is read. Past this many buckets, a
# bucket grows instead.
_MAX_BUCKETS = 256
# DuckDB runs inside the shared worker process, so it gets a bounded slice and spills to the run's
# temporary directory past it.
_DUCKDB_THREADS = 2
_DUCKDB_MEMORY_LIMIT = "1GB"
_CLOSE_ORDER = "_ph_close_order"
_CLOSE_AT = "_ph_close_at"
_CLOSE_PARTITION = "_ph_close_partition"


@frozen
class HistoryFinalizeResult:
    staged_rows: int
    inserted_rows: int
    closed_rows: int
    backwards_rows: int
    buckets: int


@frozen
class _BucketPlan:
    inserts: pa.Table
    closes: pa.Table
    backwards_rows: int


class HistoryWriter:
    """SCD Type 2 history in two steps: `append` stages each batch, `finalize` turns the run into versions.

    A close per batch rewrites every history file that holds a changed key, so its cost grows with the
    table on every batch. Here each batch only appends to a staging table, and `finalize` writes the
    run once per bucket of keys: an append of the new versions, then one close merge.

    A row becomes a version when its `order_column` value is greater than that of its key's newest open
    version, or when its key has no open version. Rows with the same key and order value collapse into
    the last one staged, which drops incremental re-reads and a redelivered batch. Every open version
    that is not its key's newest closes at the next version after it, staged or open. Between the
    append and the close a key has more than one open version, so a re-run after a crash there inserts
    nothing it already wrote and still closes each old version at the right time. Staged rows are
    deleted only after the close committed.
    """

    def __init__(
        self,
        table: "DeltaTableRef",
        staging: "DeltaTableRef",
        *,
        primary_keys: Sequence[str],
        valid_from_column: str,
        valid_to_column: str,
        order_column: str | None = None,
        partition_column: str | None = None,
        current_partition: str | None = None,
        bucket_target_mib: float = DEFAULT_BUCKET_TARGET_MIB,
    ) -> None:
        """`order_column` orders a key's versions and defaults to `valid_from_column` (an incremental
        cursor); CDC passes its change sequence. `partition_column` partitions a new history table into
        `current_partition` for open rows and the `YYYY-MM` month a version ended for closed rows."""
        if partition_column is not None and current_partition is None:
            raise ValueError("A partitioned history table needs the name of its current partition")
        if not primary_keys:
            raise ValueError("A history table needs a primary key")
        self._table = table
        self._staging = staging
        self._logger = table.logger
        self._primary_keys = [normalize_column_name(key) for key in primary_keys]
        self._valid_from = valid_from_column
        self._valid_to = valid_to_column
        self._order = order_column or valid_from_column
        self._partition_column = partition_column
        self._current_partition = current_partition
        self._bucket_target_mib = bucket_target_mib

    async def append(self, data: pa.Table, *, run_uuid: str, batch_index: int) -> None:
        """Stage one batch. Each row needs the key columns, `valid_from` and the order column.

        The commit carries the batch's `run_uuid` and `batch_index`, so the load path's redelivery
        check finds it on the staging table. A batch staged twice still makes one version per row.
        """
        if data.num_rows == 0:
            return
        data = relax_batch_nullability(realign_decimal_buffers(data))
        missing = [c for c in (*self._primary_keys, self._valid_from, self._order) if c not in data.column_names]
        if missing:
            raise ValueError(f"History batch is missing column(s) {missing}")
        taken = [c for c in _STAGING_COLUMNS if c in data.column_names]
        if taken:
            raise ValueError(f"History batch has column(s) {taken}, which the staging table writes itself")
        data = data.drop_columns([c for c in (self._valid_to, self._partition_column) if c in data.column_names])
        staging_table = await self._staging.get_delta_table()
        # Creating the table commits version 0, so the first append is version 1.
        first_row = (staging_table.version() + 1 if staging_table is not None else 1) << 32
        data = data.append_column(
            STAGED_BATCH_COLUMN, pa.repeat(pa.scalar(f"{run_uuid}:{batch_index}"), data.num_rows)
        ).append_column(STAGED_ROW_COLUMN, pa.array(np.arange(first_row, first_row + data.num_rows, dtype=np.int64)))

        if staging_table is None:
            staging_table = await asyncio.to_thread(
                deltalake.DeltaTable.create,
                table_uri=await self._staging.get_table_uri(),
                schema=data.schema,
                storage_options=self._staging.get_storage_options(),
                configuration=DELTA_TABLE_PROPERTIES,
            )
            self._staging.adopt_created_table(staging_table)
        else:
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

    async def finalize(self) -> HistoryFinalizeResult:
        """Write every staged row into the history table as versions, then delete the staged rows."""
        staging_table = await self._staging.get_delta_table()
        staged_mib = live_size_mib(staging_table) if staging_table is not None else 0.0
        if staging_table is None or staged_mib == 0:
            return HistoryFinalizeResult(staged_rows=0, inserted_rows=0, closed_rows=0, backwards_rows=0, buckets=0)

        # Without file sizes in the log, one bucket keeps the run correct at the cost of its memory.
        buckets = min(_MAX_BUCKETS, max(1, int(-(-staged_mib // self._bucket_target_mib)))) if staged_mib else 1
        staged_rows = inserted_rows = backwards_rows = 0
        closes: list[pa.Table] = []
        # Read before the first append: a table this run creates holds no open version of any staged key.
        history_table = await self._table.get_delta_table()
        # A table created before partitioning stays unpartitioned, so its rows get no partition column.
        partition_versions = self._partition_column is not None and (
            history_table is None or self._partitioned(history_table)
        )
        with tempfile.TemporaryDirectory(prefix="history-finalize-") as name:
            directory = Path(name)
            staging_dataset = staging_table.to_pyarrow_dataset()
            bucket_paths, batch_tags = await asyncio.to_thread(self._spill_buckets, staging_dataset, buckets, directory)
            # With several buckets, one scan splits the open versions the same way, so no bucket scans
            # the whole current partition again.
            open_paths = (
                await asyncio.to_thread(
                    self._spill_open_versions, history_table, staging_dataset.schema, buckets, directory
                )
                if history_table is not None and buckets > 1
                else None
            )
            for index, path in enumerate(bucket_paths):
                staged = await asyncio.to_thread(_read_bucket, path)
                if staged.num_rows == 0:
                    continue
                staged_rows += staged.num_rows
                open_versions = None
                if open_paths is not None:
                    open_versions = await asyncio.to_thread(
                        self._matching_open_versions, _bucket_batches(open_paths[index]), staged, directory
                    )
                elif history_table is not None:
                    open_versions = await asyncio.to_thread(
                        self._matching_open_versions, self._scan_open_versions(history_table), staged, directory
                    )
                plan = await asyncio.to_thread(self._plan_bucket, staged, open_versions, partition_versions, directory)
                del staged
                if plan.inserts.num_rows:
                    await self._append_versions(plan.inserts)
                closes.append(plan.closes)
                inserted_rows += plan.inserts.num_rows
                backwards_rows += plan.backwards_rows

        # One close for the run, because each close rewrites every current file that holds a closed key.
        all_closes = pa.concat_tables(closes) if closes else None
        closed_rows = all_closes.num_rows if all_closes is not None else 0
        if all_closes is not None and closed_rows:
            await self._close_versions(all_closes)
        # Only after the close committed: a crash before this point leaves the rows staged for the re-run.
        await DeltaWriter(self._staging).delete_where(STAGED_BATCH_COLUMN, batch_tags)
        history_table = await self._table.get_delta_table()
        if history_table is not None:
            await ensure_table_properties(history_table, self._logger)
        result = HistoryFinalizeResult(
            staged_rows=staged_rows,
            inserted_rows=inserted_rows,
            closed_rows=closed_rows,
            backwards_rows=backwards_rows,
            buckets=buckets,
        )
        await self._logger.ainfo("history_finalize", **dataclasses.asdict(result))
        return result

    def _spill_buckets(self, dataset: ds.Dataset, buckets: int, directory: Path) -> tuple[list[Path], set[str]]:
        batch_tags: set[str] = set()

        def _tag(batch: pa.RecordBatch) -> pa.RecordBatch:
            batch_tags.update(str(tag) for tag in pc.unique(batch.column(STAGED_BATCH_COLUMN)).drop_null().to_pylist())
            return batch

        scanner = dataset.scanner(batch_readahead=1, fragment_readahead=1, use_threads=False)
        batches = (_tag(batch) for batch in scanner.to_batches())
        paths = self._spill(batches, dataset.schema, buckets, directory, "staged")
        return paths, batch_tags

    def _spill_open_versions(
        self, history_table: deltalake.DeltaTable, staged_schema: pa.Schema, buckets: int, directory: Path
    ) -> list[Path]:
        # Keys take the staged types, so a key hashes to the same bucket on both sides.
        key_types = {key: staged_schema.field(key).type for key in self._primary_keys}
        batches = (
            pa.RecordBatch.from_arrays(
                [
                    batch.column(name).cast(key_types[name]) if name in key_types else batch.column(name)
                    for name in batch.schema.names
                ],
                names=batch.schema.names,
            )
            for batch in self._scan_open_versions(history_table)
        )
        schema = self._open_versions_schema(history_table, key_types)
        return self._spill(batches, schema, buckets, directory, "open")

    def _spill(
        self, batches: Iterable[pa.RecordBatch], schema: pa.Schema, buckets: int, directory: Path, name: str
    ) -> list[Path]:
        """Write each batch's rows into one file per bucket of key hash."""
        paths = [directory / f"{name}-{index}.arrow" for index in range(buckets)]
        sinks = [pa.OSFile(str(path), "wb") for path in paths]
        writers = [pa.ipc.new_file(sink, schema) for sink in sinks]
        key_list = ", ".join(f"k{index}" for index in range(len(self._primary_keys)))
        try:
            with _connect(directory) as connection:
                for batch in batches:
                    if batch.num_rows == 0:
                        continue
                    if buckets == 1:
                        writers[0].write_batch(batch)
                        continue
                    connection.register("keys", _positional(pa.Table.from_batches([batch]), self._primary_keys))
                    bucket_ids = (
                        connection.execute(f"SELECT hash({key_list}) % {buckets} FROM keys")
                        .arrow()
                        .read_all()
                        .column(0)
                    )
                    connection.unregister("keys")
                    # One sort per batch, then a slice per bucket, instead of a filter pass per bucket.
                    order = pc.sort_indices(bucket_ids)
                    sorted_batch = batch.take(order)
                    sorted_ids = bucket_ids.take(order).to_numpy()
                    starts = np.searchsorted(sorted_ids, np.arange(buckets + 1))
                    for index, writer in enumerate(writers):
                        if starts[index + 1] > starts[index]:
                            writer.write_batch(
                                sorted_batch.slice(int(starts[index]), int(starts[index + 1] - starts[index]))
                            )
        finally:
            for writer in writers:
                writer.close()
            for sink in sinks:
                sink.close()
        return paths

    def _open_versions_schema(
        self, history_table: deltalake.DeltaTable, key_types: dict[str, pa.DataType] | None = None
    ) -> pa.Schema:
        history_schema = pyarrow_schema_from_arrow_exportable(history_table.schema())
        columns = list(dict.fromkeys([*self._primary_keys, self._order, self._valid_from]))
        missing = [column for column in columns if column not in history_schema.names]
        if missing:
            # Without these columns every staged row would look new and duplicate its key's versions.
            raise ValueError(f"History table is missing column(s) {missing}")
        return pa.schema(
            [pa.field(column, (key_types or {}).get(column, history_schema.field(column).type)) for column in columns]
        )

    def _scan_open_versions(self, history_table: deltalake.DeltaTable) -> Iterator[pa.RecordBatch]:
        """Key, order and `valid_from` of every open version, one bounded batch at a time."""
        columns = self._open_versions_schema(history_table).names
        row_filter = ds.field(self._valid_to).is_null()
        if self._partitioned(history_table):
            row_filter = row_filter & (ds.field(str(self._partition_column)) == self._current_partition)
        scanner = history_table.to_pyarrow_dataset().scanner(
            columns=columns, filter=row_filter, batch_readahead=1, fragment_readahead=1, use_threads=False
        )
        return iter(scanner.to_batches())

    def _matching_open_versions(
        self, batches: Iterable[pa.RecordBatch], staged: pa.Table, directory: Path
    ) -> pa.Table | None:
        """The open versions among `batches` whose key is staged in this bucket."""
        matches: list[pa.Table] = []
        with _connect(directory) as connection:
            connection.register("staged_keys", _positional(staged, self._primary_keys))
            for batch in batches:
                if batch.num_rows == 0:
                    continue
                table = pa.Table.from_batches([batch])
                connection.register(
                    "open_batch",
                    _positional(table, self._primary_keys).append_column(
                        "batch_index", pa.array(np.arange(table.num_rows, dtype=np.int64))
                    ),
                )
                matched = (
                    connection.execute(
                        "SELECT batch_index FROM open_batch o WHERE EXISTS "
                        f"(SELECT 1 FROM staged_keys s WHERE {_null_safe_keys('o', 's', len(self._primary_keys))})"
                    )
                    .arrow()
                    .read_all()
                )
                connection.unregister("open_batch")
                # Taken in Arrow, so the close merge compares keys of the table's own types.
                matches.append(table.take(matched.column(0)))
        return pa.concat_tables(matches) if matches else None

    def _plan_bucket(
        self, staged: pa.Table, open_versions: pa.Table | None, partition_versions: bool, directory: Path
    ) -> _BucketPlan:
        key_count = len(self._primary_keys)
        keys = ", ".join(f"k{index}" for index in range(key_count))
        narrow = (
            _positional(staged, self._primary_keys, self._order)
            .append_column("staged_row", staged.column(STAGED_ROW_COLUMN))
            .append_column("row_index", pa.array(np.arange(staged.num_rows, dtype=np.int64)))
        )
        if open_versions is None:
            open_versions = staged.select(list(dict.fromkeys([*self._primary_keys, self._order, self._valid_from])))
            open_versions = open_versions.slice(0, 0)
        open_rows = _positional(open_versions, self._primary_keys, self._order).append_column(
            "open_index", pa.array(np.arange(open_versions.num_rows, dtype=np.int64))
        )
        with _connect(directory) as connection:
            connection.register("staged", narrow)
            connection.register("open_rows", open_rows)
            connection.execute(
                f"""
                CREATE TEMP TABLE candidates AS
                WITH latest AS (
                    SELECT * FROM staged
                    QUALIFY row_number() OVER (PARTITION BY {keys}, ord ORDER BY staged_row DESC) = 1
                ),
                open_span AS (SELECT {keys}, max(ord) AS newest FROM open_rows GROUP BY {keys})
                SELECT latest.*, open_span.newest
                FROM latest LEFT JOIN open_span ON {_null_safe_keys("latest", "open_span", key_count)}
                """
            )
            plan = (
                connection.execute(
                    f"""
                    SELECT row_index, lead(row_index) OVER versions AS next_row_index
                    FROM candidates
                    WHERE newest IS NULL OR ord > newest
                    WINDOW versions AS (PARTITION BY {keys} ORDER BY ord, staged_row)
                    """
                )
                .arrow()
                .read_all()
            )
            # A key has more than one open version after a crash between the append and the close, and
            # after an older writer matched null keys with `=`. Each one closes at the version after it.
            close_rows = (
                connection.execute(
                    f"""
                    WITH opens AS (
                        SELECT {keys}, ord, min(open_index) AS open_index FROM open_rows GROUP BY {keys}, ord
                    ),
                    fresh AS (
                        SELECT c.* FROM candidates c WHERE NOT EXISTS (
                            SELECT 1 FROM opens o WHERE {_null_safe_keys("o", "c", key_count)} AND o.ord = c.ord
                        )
                    ),
                    versions AS (
                        SELECT {keys}, ord, open_index, NULL::BIGINT AS row_index, NULL::BIGINT AS staged_row
                        FROM opens
                        UNION ALL
                        SELECT {keys}, ord, NULL::BIGINT, row_index, staged_row FROM fresh
                    ),
                    successors AS (
                        SELECT
                            open_index,
                            lead(row_index) OVER following AS next_row_index,
                            lead(open_index) OVER following AS next_open_index
                        FROM versions
                        WINDOW following AS (PARTITION BY {keys} ORDER BY ord, staged_row NULLS FIRST)
                    )
                    SELECT open_index, next_row_index, next_open_index FROM successors
                    WHERE open_index IS NOT NULL AND (next_row_index IS NOT NULL OR next_open_index IS NOT NULL)
                    """
                )
                .arrow()
                .read_all()
            )
            backwards_row = connection.execute("SELECT count(*) FROM candidates WHERE ord < newest").fetchone()
        backwards_rows = int(backwards_row[0]) if backwards_row else 0

        inserts = staged.take(plan.column("row_index")).drop_columns(list(_STAGING_COLUMNS))
        valid_to = staged.column(self._valid_from).take(plan.column("next_row_index"))
        inserts = inserts.append_column(pa.field(self._valid_to, valid_to.type), valid_to)
        closed = open_versions.take(close_rows.column("open_index"))
        close_at = pc.coalesce(
            staged.column(self._valid_from).take(close_rows.column("next_row_index")),
            pc.cast(open_versions.column(self._valid_from), valid_to.type).take(close_rows.column("next_open_index")),
        )
        closes = closed.select(self._primary_keys).append_column(_CLOSE_ORDER, closed.column(self._order))
        closes = closes.append_column(pa.field(_CLOSE_AT, valid_to.type), close_at)
        if partition_versions and self._partition_column is not None:
            inserts = inserts.append_column(
                self._partition_column,
                pc.if_else(pc.is_null(valid_to), self._current_partition, _month(valid_to)),
            )
            closes = closes.append_column(_CLOSE_PARTITION, _month(close_at))
        return _BucketPlan(inserts=inserts, closes=closes, backwards_rows=backwards_rows)

    async def _append_versions(self, inserts: pa.Table) -> None:
        history_table = await self._table.get_delta_table()
        if history_table is None:
            history_table = await asyncio.to_thread(
                deltalake.DeltaTable.create,
                table_uri=await self._table.get_table_uri(),
                schema=inserts.schema,
                partition_by=[self._partition_column] if self._partition_column else None,
                storage_options=self._table.get_storage_options(),
                configuration=DELTA_TABLE_PROPERTIES,
            )
            self._table.adopt_created_table(history_table)
        else:
            history_table = await evolve_delta_schema(history_table, inserts.schema)
            inserts = align_incoming_decimals_to_delta(inserts, history_table.schema())
        await asyncio.to_thread(
            deltalake.write_deltalake,
            table_or_uri=history_table,
            data=inserts,
            mode="append",
            schema_mode="merge",
        )

    async def _close_versions(self, closes: pa.Table) -> None:
        history_table = await self._table.get_delta_table()
        assert history_table is not None
        predicate_parts = [
            f"target.{self._valid_to} IS NULL",
            *_merge_predicate_ops(self._primary_keys),
            f"target.{self._order} = source.{_CLOSE_ORDER}",
        ]
        updates = {self._valid_to: f"source.{_CLOSE_AT}"}
        if self._partitioned(history_table):
            # Open versions only sit in the current partition, so the merge reads and rewrites no other.
            predicate_parts.append(f"target.{self._partition_column} = '{self._current_partition}'")
            updates[str(self._partition_column)] = f"source.{_CLOSE_PARTITION}"
        predicate = " AND ".join(predicate_parts)
        target = history_table

        def _merge() -> dict:
            return (
                target.merge(
                    source=closes,
                    source_alias="source",
                    target_alias="target",
                    predicate=predicate,
                    streamed_exec=False,
                    **delta_merge_spill_kwargs(),
                )
                .when_matched_update(updates=updates)
                .execute()
            )

        stats = await execute_with_conflict_retry(target, _merge, "HistoryWriter.finalize: close merge", self._logger)
        await self._logger.adebug(f"History finalize close stats: {json.dumps(stats)}")

    def _partitioned(self, delta_table: deltalake.DeltaTable) -> bool:
        partition_columns = delta_table.metadata().partition_columns or []
        return self._partition_column is not None and self._partition_column in partition_columns


def _read_bucket(path: Path) -> pa.Table:
    with pa.memory_map(str(path)) as source:
        return pa.ipc.open_file(source).read_all()


def _bucket_batches(path: Path) -> Iterator[pa.RecordBatch]:
    with pa.memory_map(str(path)) as source:
        reader = pa.ipc.open_file(source)
        for index in range(reader.num_record_batches):
            yield reader.get_batch(index)


def _connect(directory: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(
        config={"threads": _DUCKDB_THREADS, "memory_limit": _DUCKDB_MEMORY_LIMIT, "temp_directory": str(directory)}
    )


def _positional(table: pa.Table, keys: Sequence[str], order: str | None = None) -> pa.Table:
    """The key columns as `k0..kN` and the order column as `ord`, so no source column name reaches SQL."""
    columns = {f"k{index}": table.column(key) for index, key in enumerate(keys)}
    if order is not None:
        columns["ord"] = table.column(order)
    return pa.table(columns)


def _null_safe_keys(left: str, right: str, key_count: int) -> str:
    return " AND ".join(f"{left}.k{index} IS NOT DISTINCT FROM {right}.k{index}" for index in range(key_count))


def _month(values: pa.ChunkedArray | pa.Array) -> pa.ChunkedArray | pa.Array:
    return pc.strftime(values, format="%Y-%m")
