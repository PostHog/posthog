"""Bounded-memory building blocks for the repartition rewrite.

The rewrite copies every row of a live Delta table into a temp table under a new partition scheme.
Its memory must depend on the byte budget only, not on the table's size, its file count or the rows
already written. This module holds the three parts that make that true:

* `SourceReader` reads one source parquet file at a time, by row group, in batches sized from a
  byte budget. Nothing is held for a file after its last batch, so the parquet footer and schema of
  each file are freed before the next file opens. A `pyarrow.dataset` over the whole table keeps
  each fragment's footer once it has scanned it, which grows with every file read.
* `PartitionedFileWriter` routes rows to one parquet file per target partition. It caps the open
  files and the rows they buffer, and it rolls a file over at a target size.
* `TempTableCommitter` commits the closed files as Add actions, with no data rewrite. Each commit
  also records which source files it completes, so a resumed rewrite skips whole source files
  instead of counting rows.

The module has no Django imports, so the local reproduction can drive it directly.
"""

from __future__ import annotations

import re
import json
import math
import time
import uuid
import decimal
import hashlib
import datetime
from collections import OrderedDict, deque
from collections.abc import Generator, Iterator, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, cast

import pyarrow as pa
import deltalake
import pyarrow.fs as pa_fs
import pyarrow.compute as pc
import pyarrow.parquet as pq
from deltalake.fs import DeltaStorageHandler
from deltalake.transaction import AddAction, CommitProperties

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY

MB = 1024 * 1024

# Commit metadata key that lists the source files a temp commit completes.
SOURCE_FILES_METADATA_KEY = "repartition_source_files"

# Delta-rs truncates string statistics at this many UTF-8 bytes. The same bound keeps the stats of a
# column of large JSON strings small, both in the log and while a file is open.
STRING_STATS_MAX_BYTES = 64

# Delta's default for `delta.dataSkippingNumIndexedCols`.
DEFAULT_NUM_INDEXED_COLS = 32

# The object-store output stream buffers this much before it uploads a multipart part, and the
# parquet writer keeps per-column state too. Counted per open file when the open-file cap is sized.
_OPEN_FILE_OVERHEAD_BYTES = 8 * MB

# Reader features this path cannot honour. A deletion vector hides rows that the parquet file still
# holds, and column mapping renames physical columns, so reading the files directly would be wrong.
UNSUPPORTED_READER_FEATURES = frozenset({"deletionVectors", "columnMapping"})

_SAFE_PARTITION_DIR = re.compile(r"^[A-Za-z0-9_.\-]+$")


class UnsupportedSourceTableError(Exception):
    """The live table uses a Delta feature that a file-by-file copy would get wrong."""


@frozen
class StreamBudget:
    """Byte limits for one rewrite. Every in-memory term of the rewrite is bounded by one of these."""

    batch_bytes: int
    buffer_bytes: int
    row_group_bytes: int
    max_open_files: int
    target_file_bytes: int
    commit_bytes: int
    max_source_files_per_commit: int

    @staticmethod
    def from_budget(budget_bytes: int, *, target_file_bytes: int = 128 * MB) -> StreamBudget:
        """Divide one byte budget across the read batch, the write buffers and the open files.

        Half goes to buffered rows, a quarter to open-file overhead, and an eighth to the decoded
        read batch. The rest covers the batch copies that routing and casting make.
        """
        budget_bytes = max(budget_bytes, 64 * MB)
        buffer_bytes = budget_bytes // 2
        return StreamBudget(
            batch_bytes=max(budget_bytes // 8, 1 * MB),
            buffer_bytes=buffer_bytes,
            row_group_bytes=max(min(64 * MB, buffer_bytes // 4), 1 * MB),
            max_open_files=max(2, min(64, (budget_bytes // 4) // _OPEN_FILE_OVERHEAD_BYTES)),
            target_file_bytes=target_file_bytes,
            commit_bytes=max(8 * target_file_bytes, 1024 * MB),
            max_source_files_per_commit=2_000,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "batch_bytes": self.batch_bytes,
            "buffer_bytes": self.buffer_bytes,
            "row_group_bytes": self.row_group_bytes,
            "max_open_files": self.max_open_files,
            "target_file_bytes": self.target_file_bytes,
        }


@frozen
class SourceFile:
    path: str
    size: int
    num_records: int | None
    partition_values: Mapping[str, str | None]


@frozen
class WrittenFile:
    action: AddAction
    num_records: int


def check_source_supported(delta_table: deltalake.DeltaTable) -> None:
    protocol = delta_table.protocol()
    features = set(protocol.reader_features or []) & UNSUPPORTED_READER_FEATURES
    if features:
        raise UnsupportedSourceTableError(f"the live table uses reader features {sorted(features)}")


def plan_source_files(delta_table: deltalake.DeltaTable) -> list[SourceFile]:
    """The live data files of the loaded version, from the log only, in a stable order.

    Path order makes the plan the same for every attempt against the same version.
    """
    actions = pa.table(delta_table.get_add_actions(flatten=False))
    names = actions.schema.names
    paths = actions.column("path").to_pylist()
    sizes = actions.column("size_bytes").to_pylist()
    counts = actions.column("num_records").to_pylist() if "num_records" in names else [None] * len(paths)
    partitions = actions.column("partition_values").to_pylist() if "partition_values" in names else [None] * len(paths)
    files = [
        SourceFile(path=path, size=size or 0, num_records=count, partition_values=dict(values or {}))
        for path, size, count, values in zip(paths, sizes, counts, partitions)
        if path
    ]
    files.sort(key=lambda f: f.path)
    return files


def copied_source_files(temp_uri: str, storage_options: dict[str, str]) -> frozenset[str] | None:
    """The source files the temp table already holds in full, read from its commit metadata.

    None means the record cannot be trusted: a commit without it (a temp table that an older
    rewrite wrote), or a history that does not reach back to the table's creation.
    """
    temp = deltalake.DeltaTable(temp_uri, storage_options=storage_options)
    copied: set[str] = set()
    versions: set[int] = set()
    for entry in temp.history():
        version = entry.get("version")
        if isinstance(version, int):
            versions.add(version)
        if entry.get("operation") == "CREATE TABLE":
            continue
        raw = entry.get(SOURCE_FILES_METADATA_KEY)
        if raw is None:
            return None
        copied.update(json.loads(raw))
    if versions != set(range(temp.version() + 1)):
        return None
    return frozenset(copied)


def resume_blocker(
    *,
    live_sources: Sequence[SourceFile],
    live_schema: pa.Schema,
    temp_uri: str,
    storage_options: dict[str, str],
    copied: frozenset[str],
    temp_rows: int,
) -> str | None:
    """Why temp cannot be resumed against the live table as it is now, or None when it can.

    Delta data files never change, so a copied file that is still live still holds exactly the rows
    temp took from it. A sync that committed since the checkpoint only blocks the resume when it
    removed a copied file (a merge rewrote it) or added a column temp does not have.
    """
    by_path = {source.path: source for source in live_sources}
    if any(path not in by_path for path in copied):
        return "copied_file_no_longer_live"
    temp = deltalake.DeltaTable(temp_uri, storage_options=storage_options)
    if not set(live_schema.names) - {PARTITION_KEY} <= set(arrow_schema_of(temp.schema()).names):
        return "live_schema_changed"
    counts = [by_path[path].num_records for path in copied]
    if all(count is not None for count in counts) and sum(count or 0 for count in counts) != temp_rows:
        return "temp_rows_do_not_match_copied_files"
    return None


def arrow_schema_of(delta_schema: deltalake.Schema) -> pa.Schema:
    # `to_arrow` returns an arro3 schema; pyarrow imports it through the Arrow C interface, which
    # the stubs do not model.
    return pa.schema(delta_schema.to_arrow())  # type: ignore[arg-type]


def storage_filesystem(table_uri: str, storage_options: dict[str, str], **kwargs: Any) -> pa_fs.FileSystem:
    """A pyarrow filesystem rooted at the table, on the same object store client delta-rs uses."""
    return pa_fs.PyFileSystem(DeltaStorageHandler(table_uri, storage_options, **kwargs))


class SourceReader:
    """Reads source files as tables aligned to the live table's schema, in plan order.

    A small file is fetched whole on a worker thread, a few files ahead, under a cap on the bytes
    fetched and not yet consumed. Decoding stays on the consumer so prefetched files cannot retain
    whole decoded tables. Over-fragmented tables are made of such files, and reading them one at a
    time pays one round trip per file. A large file is read by row group, in batches sized from the
    byte budget, and is never prefetched.
    """

    def __init__(
        self,
        *,
        filesystem: pa_fs.FileSystem,
        schema: pa.Schema,
        batch_bytes: int,
        max_batch_rows: int = 100_000,
        prefetch_bytes: int | None = None,
        max_prefetch_files: int = 64,
        read_threads: int = 8,
    ) -> None:
        self._filesystem = filesystem
        self._schema = schema
        self._batch_bytes = batch_bytes
        self._max_batch_rows = max_batch_rows
        # Compressed bytes. A file decodes to a few times its size, so this stays well under the batch
        # budget, and one file larger than this is streamed instead of prefetched.
        self._prefetch_bytes = prefetch_bytes if prefetch_bytes is not None else max(batch_bytes // 8, 1 * MB)
        self._max_prefetch_files = max_prefetch_files
        self._read_threads = read_threads
        # Decoded rows can be wider than the parquet footer says (dictionary pages expand), so the
        # widest row seen so far also sizes the next file's batches.
        self._observed_row_bytes = 0.0

    def batch_rows_for(self, metadata: pq.FileMetaData) -> int:
        row_bytes = self._observed_row_bytes
        for index in range(metadata.num_row_groups):
            group = metadata.row_group(index)
            if group.num_rows:
                row_bytes = max(row_bytes, group.total_byte_size / group.num_rows)
        if row_bytes <= 0:
            return self._max_batch_rows
        return max(1, min(self._max_batch_rows, int(self._batch_bytes // row_bytes)))

    def iter_sources(self, sources: Sequence[SourceFile]) -> Generator[tuple[SourceFile, Iterator[pa.Table]]]:
        """Each source with an iterator over its tables, in order. Consume each before the next."""
        pool = ThreadPoolExecutor(max_workers=self._read_threads, thread_name_prefix="repartition-read")
        pending: deque[tuple[SourceFile, Future[bytes] | None]] = deque()
        in_flight = 0
        position = 0
        try:
            while position < len(sources) or pending:
                while position < len(sources) and len(pending) < self._max_prefetch_files:
                    source = sources[position]
                    if source.size > self._prefetch_bytes:
                        pending.append((source, None))
                    elif pending and in_flight + source.size > self._prefetch_bytes:
                        break
                    else:
                        pending.append((source, pool.submit(self._fetch_small, source)))
                        in_flight += source.size
                    position += 1
                source, future = pending.popleft()
                if future is None:
                    yield source, self.iter_tables(source)
                else:
                    data = future.result()
                    in_flight -= source.size
                    yield source, self._iter_buffer(data, source)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    def iter_tables(self, source: SourceFile) -> Iterator[pa.Table]:
        with self._filesystem.open_input_file(source.path) as handle:
            yield from self._iter_parquet(pq.ParquetFile(handle, pre_buffer=True), source)

    def _fetch_small(self, source: SourceFile) -> bytes:
        with self._filesystem.open_input_file(source.path) as handle:
            return handle.read()

    def _iter_buffer(self, data: bytes, source: SourceFile) -> Iterator[pa.Table]:
        yield from self._iter_parquet(pq.ParquetFile(pa.BufferReader(data)), source)

    def _iter_parquet(self, parquet: pq.ParquetFile, source: SourceFile) -> Iterator[pa.Table]:
        batch_rows = self.batch_rows_for(parquet.metadata)
        for batch in parquet.iter_batches(batch_size=batch_rows, use_threads=False):
            if batch.num_rows == 0:
                continue
            yield self._conform(pa.Table.from_batches([batch]), source)

    def _conform(self, table: pa.Table, source: SourceFile) -> pa.Table:
        conformed = conform_to_schema(table, self._schema, source.partition_values)
        self._observed_row_bytes = max(self._observed_row_bytes, conformed.nbytes / conformed.num_rows)
        return conformed


def conform_to_schema(table: pa.Table, schema: pa.Schema, partition_values: Mapping[str, str | None]) -> pa.Table:
    """Give one file's rows the table schema, the way a dataset scan over the table does.

    A file written before a column was added lacks it, so it reads as nulls. Partition columns are
    not stored in the file, so they come from the Add action's partition values.
    """
    if table.schema.names == schema.names and table.schema.types == schema.types:
        return pa.Table.from_arrays(table.columns, schema=schema)
    num_rows = table.num_rows
    columns: list[pa.ChunkedArray | pa.Array] = []
    for field in schema:
        index = table.schema.get_field_index(field.name)
        column: pa.ChunkedArray | pa.Array
        if index >= 0:
            column = table.column(index)
            if column.type != field.type:
                column = column.cast(field.type)
        elif field.name in partition_values and partition_values[field.name] is not None:
            column = pa.array([partition_values[field.name]] * num_rows, pa.string()).cast(field.type)
        else:
            column = pa.nulls(num_rows, field.type)
        columns.append(column)
    return pa.Table.from_arrays(columns, schema=schema)


def _stats_columns(schema: pa.Schema, configuration: Mapping[str, str | None]) -> list[str]:
    """The columns whose stats an Add action carries: the table's selection, without nested columns.

    Delta nests the stats of a struct column field by field, and a flat value there is a log that
    delta-rs refuses to commit. The pipeline flattens nested values to JSON strings before they
    reach a table, so a nested column here is rare and loses only its pruning.
    """
    data_columns = [name for name in schema.names if name != PARTITION_KEY]
    named = configuration.get("delta.dataSkippingStatsColumns")
    if named:
        wanted = {part.strip().strip("`") for part in named.split(",") if part.strip()}
        selected = [name for name in data_columns if name in wanted]
    else:
        raw_count = configuration.get("delta.dataSkippingNumIndexedCols")
        count = int(raw_count) if raw_count else DEFAULT_NUM_INDEXED_COLS
        selected = data_columns if count < 0 else data_columns[:count]
    return [name for name in selected if not pa.types.is_nested(schema.field(name).type)]


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _string_upper_bound(value: str) -> str | None:
    """The smallest string up to `STRING_STATS_MAX_BYTES` that is not less than `value`.

    A truncated prefix sorts below the value, so its last character is raised by one. None when no
    character can be raised, which leaves the column without a max.
    """
    prefix = _truncate_utf8(value, STRING_STATS_MAX_BYTES)
    if prefix == value:
        return value
    chars = list(prefix)
    while chars:
        code = ord(chars.pop()) + 1
        if 0xD800 <= code <= 0xDFFF:
            code = 0xE000
        if code <= 0x10FFFF:
            candidate = "".join(chars) + chr(code)
            if len(candidate.encode("utf-8")) <= STRING_STATS_MAX_BYTES:
                return candidate
    return None


@frozen
class StatBounds:
    """JSON-ready min and max for one column. None means the bound is left out."""

    low: Any
    high: Any


class _ColumnStats:
    """Running min, max and null count of one column across the batches of one output file.

    A reader skips a file whose min/max rule out its filter, so a bound that misses one value loses
    that row from reads and turns its merge into a duplicate insert. Each bound is exact or looser,
    and matches what delta-rs writes where delta-rs is safe.

    A bound is left out only where JSON cannot hold it (infinity). That is not free: delta-rs's
    pyarrow reader turns a missing bound into a null guarantee and skips the file for every filter
    on the column, the same as it does for delta-rs's own stats in that case.
    """

    __slots__ = ("kind", "minimum", "maximum", "null_count", "min_unbounded", "max_unbounded")

    def __init__(self, data_type: pa.DataType) -> None:
        self.kind = _stats_kind(data_type)
        self.minimum: Any = None
        self.maximum: Any = None
        self.null_count = 0
        self.min_unbounded = False
        self.max_unbounded = False

    def update(self, column: pa.ChunkedArray) -> None:
        self.null_count += column.null_count
        if self.kind is None or column.null_count == len(column):
            return
        if self.kind == "float":
            # Same as delta-rs and the parquet footer: NaN is left out of the bounds. JSON has no
            # infinity, so a file holding one has no bound on that side.
            self.min_unbounded = self.min_unbounded or bool(
                pc.any(pc.equal(column, pa.scalar(-math.inf, column.type))).as_py()
            )
            self.max_unbounded = self.max_unbounded or bool(
                pc.any(pc.equal(column, pa.scalar(math.inf, column.type))).as_py()
            )
            column = pc.filter(column, pc.is_finite(column))
            if len(column) == 0:
                return
        result = pc.min_max(column)
        low, high = result["min"].as_py(), result["max"].as_py()
        if low is None or high is None:
            return
        if self.kind == "string":
            low = _truncate_utf8(low, STRING_STATS_MAX_BYTES)
            # With no short upper bound the exact value is kept, as delta-rs does.
            high = _string_upper_bound(high) or high
        self.minimum = low if self.minimum is None or low < self.minimum else self.minimum
        self.maximum = high if self.maximum is None or high > self.maximum else self.maximum

    def json_values(self) -> StatBounds:
        if self.kind is None or self.minimum is None:
            return StatBounds(low=None, high=None)
        return StatBounds(
            low=None if self.min_unbounded else _json_stat(self.minimum),
            high=None if self.max_unbounded else _json_stat(self.maximum),
        )


def _stats_kind(data_type: pa.DataType) -> str | None:
    if pa.types.is_integer(data_type):
        return "int"
    if pa.types.is_floating(data_type):
        return "float"
    if pa.types.is_decimal(data_type):
        return "decimal"
    if pa.types.is_string(data_type) or pa.types.is_large_string(data_type):
        return "string"
    if pa.types.is_boolean(data_type):
        return "bool"
    if pa.types.is_date32(data_type):
        return "date"
    if pa.types.is_timestamp(data_type) and data_type.unit == "us":
        return "timestamp"
    return None


def _json_stat(value: Any) -> Any:
    # Same text forms delta-rs writes, so readers that parse its stats parse these too. A decimal
    # stays a `Decimal` until `_dumps_stats` writes it as an exact JSON number.
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            return str(value)
        return value.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def _dumps_stats(stats: dict[str, Any]) -> str:
    """JSON for an Add action's stats, with each decimal written as its exact JSON number.

    delta-rs writes a decimal bound through a float. The float can round to the inner side of the
    real bound, and from about 1e16 delta-rs's own reader parses it as null. The exact number text
    is valid JSON and parses back to the exact value.
    """
    # A random token, so no string value in the stats can look like a placeholder.
    token = uuid.uuid4().hex
    numbers: list[str] = []

    def default(value: Any) -> str:
        if isinstance(value, decimal.Decimal) and value.is_finite():
            numbers.append(format(value, "f"))
            return f"{token}{len(numbers) - 1}"
        raise TypeError(f"cannot write {type(value).__name__} into Delta stats")

    text = json.dumps(stats, default=default)
    return re.sub(f'"{token}(\\d+)"', lambda match: numbers[int(match.group(1))], text)


class _OpenFile:
    """One parquet file in the temp table, open for one target partition."""

    def __init__(
        self,
        *,
        filesystem: pa_fs.FileSystem,
        path: str,
        partition_value: str | None,
        file_schema: pa.Schema,
        stats_columns: Sequence[str],
    ) -> None:
        self.path = path
        self.partition_value = partition_value
        self._sink = filesystem.open_output_stream(path)
        self._writer = pq.ParquetWriter(self._sink, file_schema, compression="snappy")
        self._stats = {name: _ColumnStats(file_schema.field(name).type) for name in stats_columns}
        self.pending: list[pa.Table] = []
        self.pending_bytes = 0
        self.num_records = 0

    @property
    def written_bytes(self) -> int:
        return self._sink.tell()

    def append(self, table: pa.Table) -> None:
        self.pending.append(table)
        self.pending_bytes += table.nbytes
        self.num_records += table.num_rows
        for name, stats in self._stats.items():
            stats.update(table.column(name))

    def flush_row_group(self) -> None:
        if not self.pending:
            return
        combined = self.pending[0] if len(self.pending) == 1 else pa.concat_tables(self.pending)
        self.pending = []
        self.pending_bytes = 0
        self._writer.write_table(combined, row_group_size=max(combined.num_rows, 1))

    def close(self) -> WrittenFile:
        self.flush_row_group()
        self._writer.close()
        size = self._sink.tell()
        self._sink.close()
        stats: dict[str, Any] = {"numRecords": self.num_records, "minValues": {}, "maxValues": {}, "nullCount": {}}
        for name, column_stats in self._stats.items():
            stats["nullCount"][name] = column_stats.null_count
            bounds = column_stats.json_values()
            if bounds.low is not None:
                stats["minValues"][name] = bounds.low
            if bounds.high is not None:
                stats["maxValues"][name] = bounds.high
        action = AddAction(
            self.path,
            size,
            {PARTITION_KEY: self.partition_value},
            int(time.time() * 1000),
            True,
            _dumps_stats(stats),
        )
        return WrittenFile(action=action, num_records=self.num_records)

    def abort(self) -> None:
        try:
            self._writer.close()
        finally:
            self._sink.close()


def _partition_dir(value: str | None) -> str:
    # The Add action carries the partition value, so the directory name only has to be unique and
    # safe. A value with characters that need URI encoding gets a hashed name instead, because the
    # log stores paths encoded and a literal `%` in an object key would not round-trip.
    if value is None:
        return f"{PARTITION_KEY}=__HIVE_DEFAULT_PARTITION__"
    if _SAFE_PARTITION_DIR.match(value):
        return f"{PARTITION_KEY}={value}"
    digest = hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{PARTITION_KEY}=__h{digest[:16]}"


def split_by_partition(table: pa.Table) -> Iterator[tuple[str | None, pa.Table]]:
    keys = table.column(PARTITION_KEY)
    if keys.null_count == 0:
        first = keys[0].as_py()
        if pc.all(pc.equal(keys, first)).as_py():
            yield first, table
            return
    encoded = cast(pa.DictionaryArray, pc.dictionary_encode(keys.combine_chunks()))
    dictionary = encoded.dictionary.to_pylist()
    indices = encoded.indices
    for position, value in enumerate(dictionary):
        yield value, table.filter(pc.equal(indices, pa.scalar(position, indices.type)))
    if keys.null_count:
        yield None, table.filter(pc.is_null(indices))


class PartitionedFileWriter:
    """Writes rows into one parquet file per target partition, inside a fixed memory budget.

    Three limits bound memory however many target partitions the rows spread over:

    * at most `max_open_files` files are open; opening one more closes the least recently used;
    * one file's buffered rows become a row group at `row_group_bytes`;
    * the buffered rows of all open files never exceed `buffer_bytes`; the largest buffer is
      written out first.

    A file closes at `target_file_bytes`, on eviction, or at `finish`. Closed files wait in
    `finish`'s result until the caller commits them.
    """

    def __init__(
        self,
        *,
        filesystem: pa_fs.FileSystem,
        schema: pa.Schema,
        budget: StreamBudget,
        configuration: Mapping[str, str | None],
    ) -> None:
        self._filesystem = filesystem
        self._schema = schema
        self._file_schema = pa.schema([field.with_nullable(True) for field in schema if field.name != PARTITION_KEY])
        self._stats_columns = _stats_columns(schema, configuration)
        self._budget = budget
        self._open: OrderedDict[str | None, _OpenFile] = OrderedDict()
        self._closed: list[WrittenFile] = []
        self._buffered_bytes = 0
        self.bytes_since_commit = 0
        self.max_open_seen = 0

    @property
    def schema(self) -> pa.Schema:
        return self._schema

    @property
    def buffered_bytes(self) -> int:
        return self._buffered_bytes

    def write(self, table: pa.Table) -> None:
        """Route `table` (which holds `PARTITION_KEY`) to its partitions' files."""
        unknown = set(table.column_names) - set(self._schema.names)
        if unknown:
            # Selecting the known columns would silently drop these values from the rebuilt table.
            raise ValueError(f"rows carry columns the temp table does not have: {sorted(unknown)}")
        table = table.select(self._schema.names).cast(self._schema)
        for value, rows in split_by_partition(table):
            data = rows.drop([PARTITION_KEY]).cast(self._file_schema)
            open_file = self._file_for(value)
            open_file.append(data)
            self._buffered_bytes += data.nbytes
            if open_file.pending_bytes >= self._budget.row_group_bytes:
                self._flush(open_file)
            while self._buffered_bytes > self._budget.buffer_bytes:
                self._flush(max(self._open.values(), key=lambda f: f.pending_bytes))

    def finish(self) -> list[WrittenFile]:
        """Close every open file and hand over all files closed since the last call."""
        while self._open:
            _, open_file = self._open.popitem(last=False)
            self._close(open_file)
        closed, self._closed = self._closed, []
        self.bytes_since_commit = 0
        return closed

    def abort(self) -> list[str]:
        """Drop every open and uncommitted file. Returns their paths so the caller can delete them."""
        paths = [written.action.path for written in self._closed]
        while self._open:
            _, open_file = self._open.popitem(last=False)
            paths.append(open_file.path)
            open_file.abort()
        self._closed = []
        self._buffered_bytes = 0
        return paths

    def _file_for(self, value: str | None) -> _OpenFile:
        open_file = self._open.get(value)
        if open_file is not None:
            self._open.move_to_end(value)
            return open_file
        if len(self._open) >= self._budget.max_open_files:
            _, oldest = self._open.popitem(last=False)
            self._close(oldest)
        open_file = _OpenFile(
            filesystem=self._filesystem,
            path=f"{_partition_dir(value)}/part-{uuid.uuid4()}-c000.snappy.parquet",
            partition_value=value,
            file_schema=self._file_schema,
            stats_columns=self._stats_columns,
        )
        self._open[value] = open_file
        self.max_open_seen = max(self.max_open_seen, len(self._open))
        return open_file

    def _flush(self, open_file: _OpenFile) -> None:
        before = open_file.written_bytes
        self._buffered_bytes -= open_file.pending_bytes
        open_file.flush_row_group()
        self.bytes_since_commit += open_file.written_bytes - before
        if open_file.written_bytes >= self._budget.target_file_bytes:
            self._open.pop(open_file.partition_value, None)
            self._close(open_file)

    def _close(self, open_file: _OpenFile) -> None:
        before = open_file.written_bytes
        self._buffered_bytes -= open_file.pending_bytes
        written = open_file.close()
        self.bytes_since_commit += written.action.size - before
        self._closed.append(written)


class TempTableCommitter:
    """Commits written files to the temp table as Add actions, with the source files they complete."""

    def __init__(
        self, *, temp_uri: str, storage_options: dict[str, str], configuration: Mapping[str, str | None] | None
    ) -> None:
        self._temp_uri = temp_uri
        self._storage_options = storage_options
        self._configuration = dict(configuration or {}) or None
        self._table: deltalake.DeltaTable | None = None

    def open_or_create(self, schema: pa.Schema) -> pa.Schema:
        """Open temp, creating it with `schema` when absent. Returns the schema files must use."""
        if self._table is None:
            if deltalake.DeltaTable.is_deltatable(self._temp_uri, storage_options=self._storage_options):
                self._table = deltalake.DeltaTable(self._temp_uri, storage_options=self._storage_options)
            else:
                self._table = deltalake.DeltaTable.create(
                    self._temp_uri,
                    schema=schema,
                    partition_by=[PARTITION_KEY],
                    configuration=self._configuration,
                    storage_options=self._storage_options,
                )
        return arrow_schema_of(self._table.schema())

    def commit(self, files: Sequence[WrittenFile], source_paths: Sequence[str]) -> None:
        if self._table is None:
            raise RuntimeError("commit before the temp table was opened")
        self._table.create_write_transaction(
            [written.action for written in files],
            mode="append",
            schema=self._table.schema(),
            partition_by=[PARTITION_KEY],
            commit_properties=CommitProperties(
                custom_metadata={SOURCE_FILES_METADATA_KEY: json.dumps(list(source_paths))}
            ),
        )
        self._table.update_incremental()
