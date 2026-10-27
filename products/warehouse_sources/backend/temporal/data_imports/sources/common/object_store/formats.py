import io
import csv
import gzip
import json
import zlib
import tempfile
from collections.abc import Iterator
from typing import IO, Any, Literal, cast

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.file_parsing import (
    FILE_MODIFIED_AT_COLUMN,
    FILE_PATH_COLUMN,
    uses_brotli_compression,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    CsvOptions,
    FileFormat,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.csv_types import (
    cast_csv_columns,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.discovery import is_compressed
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    FILE_PARSE_ERROR,
    ObjectStorageError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem import StoredObject
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.incremental import (
    FILE_ROW_NUMBER_COLUMN,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.settings import (
    CSV_BLOCK_SIZE_BYTES,
    JSONL_CHUNK_BYTES,
    JSONL_CHUNK_ROWS,
    MAX_FIRST_CSV_RECORD_BYTES,
    MAX_RECORD_BYTES,
    MAX_UNPACKED_PARQUET_BYTES,
    PARQUET_BATCH_ROWS,
)

TSV_SUFFIXES = (".tsv", ".tsv.gz")
UTF8_BOM = b"\xef\xbb\xbf"
SPOOL_MEMORY_BYTES = 8 * 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024


class _PrefixedStream(io.RawIOBase):
    """Replays bytes already read from a stream before the rest of it.

    The first CSV line is read ahead to name the columns. A headerless file still needs that line
    parsed as data, so it goes back in front of the stream.
    """

    def __init__(self, prefix: bytes, rest: IO[bytes]) -> None:
        self._prefix = prefix
        self._rest = rest

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        view = memoryview(buffer)
        if self._prefix:
            count = min(len(view), len(self._prefix))
            view[:count] = self._prefix[:count]
            self._prefix = self._prefix[count:]
            return count
        data = self._rest.read(len(view))
        view[: len(data)] = data
        return len(data)


# How ClickHouse writes a null in a CSV file, and reads one back when it is unquoted.
CLICKHOUSE_CSV_NULL = "\\N"


def csv_column_names(cells: list[str], has_header: bool) -> list[str]:
    """Header names as written, made unique. A headerless file gets ClickHouse's `c1`, `c2`, ... names."""
    if not has_header:
        return [f"c{index}" for index in range(1, len(cells) + 1)]
    names: list[str] = []
    seen: set[str] = set()
    next_suffix: dict[str, int] = {}
    for index, cell in enumerate(cells, start=1):
        base = cell.strip() or f"c{index}"
        name = base
        suffix = next_suffix.get(base, 2)
        while name in seen:
            name = f"{base}_{suffix}"
            suffix += 1
        next_suffix[base] = suffix
        seen.add(name)
        names.append(name)
    return names


def _read_bounded_line(stream: IO[bytes], file_path: str, kind: str) -> bytes:
    """Read one line, refusing a line longer than `MAX_RECORD_BYTES` rather than holding it in memory."""
    line = stream.readline(MAX_RECORD_BYTES + 1)
    if len(line) > MAX_RECORD_BYTES:
        raise ObjectStorageError(
            f"{FILE_PARSE_ERROR} '{file_path}' as {kind}: a line is longer than {MAX_RECORD_BYTES:,} bytes."
        )
    return line


def _read_first_csv_record(
    stream: IO[bytes], delimiter: str, allow_double_quotes: bool, file_path: str
) -> tuple[bytes, list[str]]:
    """The first non-blank record as the bytes it spans and its fields.

    The CSV reader pulls lines until the record is complete, so a quoted field that spans lines is
    one record, and a stray quote inside an unquoted field is not mistaken for the start of one.
    """
    consumed = bytearray()

    def lines() -> Iterator[str]:
        while True:
            line = _read_bounded_line(stream, file_path, "CSV")
            if not line:
                return
            if not consumed:
                if not line.strip():
                    continue
                line = line.removeprefix(UTF8_BOM)
            if len(consumed) + len(line) > MAX_FIRST_CSV_RECORD_BYTES:
                raise ObjectStorageError(
                    f"{FILE_PARSE_ERROR} '{file_path}' as CSV: the first record is longer than "
                    f"{MAX_FIRST_CSV_RECORD_BYTES:,} bytes."
                )
            consumed.extend(line)
            yield line.decode("utf-8", errors="replace")

    if allow_double_quotes:
        reader = csv.reader(lines(), delimiter=delimiter)
    else:
        reader = csv.reader(lines(), delimiter=delimiter, quoting=csv.QUOTE_NONE)
    try:
        fields = next(reader, [])
    except csv.Error as e:
        raise ObjectStorageError(f"{FILE_PARSE_ERROR} '{file_path}' as CSV: the first record is invalid ({e}).") from e
    return bytes(consumed), fields


def iter_csv_tables(
    stream: IO[bytes],
    options: CsvOptions,
    delimiter: str = ",",
    file_path: str = "",
    logger: FilteringBoundLogger | None = None,
) -> Iterator[pa.Table]:
    """Stream a CSV file as string columns, except the columns `options.column_types` casts.

    Every other column is read as text: Arrow fixes a column's type from the first block it sees,
    so a later value that does not fit would fail the whole file mid-stream, and two files of one
    table could disagree on a type. Empty unquoted fields are null.
    """
    first_record, first_fields = _read_first_csv_record(stream, delimiter, options.allow_double_quotes, file_path)
    if not first_record:
        return
    names = csv_column_names(first_fields, options.has_header)
    body: IO[bytes] = stream if options.has_header else cast(IO[bytes], _PrefixedStream(first_record, stream))

    skipped_rows = 0
    nulled_values: dict[str, int] = {}

    def skip_invalid_row(_row: pa_csv.InvalidRow) -> Literal["skip", "error"]:
        nonlocal skipped_rows
        skipped_rows += 1
        return "skip"

    def typed(table: pa.Table) -> pa.Table:
        if not options.column_types:
            return table
        result = cast_csv_columns(table, options.column_types)
        for column, count in result.nulled_values.items():
            nulled_values[column] = nulled_values.get(column, 0) + count
        return result.table

    yielded = False
    try:
        reader = pa_csv.open_csv(
            body,
            read_options=pa_csv.ReadOptions(column_names=names, block_size=CSV_BLOCK_SIZE_BYTES, use_threads=False),
            parse_options=pa_csv.ParseOptions(
                delimiter=delimiter,
                quote_char='"' if options.allow_double_quotes else False,
                newlines_in_values=options.allow_double_quotes,
                ignore_empty_lines=True,
                invalid_row_handler=skip_invalid_row,
            ),
            convert_options=pa_csv.ConvertOptions(
                column_types=dict.fromkeys(names, pa.string()),
                null_values=["", CLICKHOUSE_CSV_NULL] if options.null_marker else [""],
                strings_can_be_null=True,
                quoted_strings_can_be_null=False,
            ),
        )
        for batch in reader:
            if batch.num_rows:
                yielded = True
                yield typed(pa.Table.from_batches([batch]))
    except pa.ArrowInvalid as e:
        if options.has_header and not yielded and "Empty CSV file" in str(e):
            # The file holds only its header. It is a table with no rows, not a broken file.
            yield typed(pa.table({name: pa.array([], pa.string()) for name in names}))
            return
        raise ObjectStorageError(f"{FILE_PARSE_ERROR} '{file_path}' as CSV: {e}") from e

    if nulled_values and logger is not None:
        # The stored column types come from a sample of the files, so a later value can fail to
        # read as its type. The value becomes null so the rest of the file still imports.
        logger.warning(
            "Read CSV values that don't match their column type as null",
            file=file_path,
            nulled_values=nulled_values,
        )

    if skipped_rows and logger is not None:
        # A row whose field count differs from the header is malformed, or the file uses another
        # delimiter. Skipping it keeps its values out of the wrong columns.
        logger.warning(
            "Skipped CSV rows whose field count differs from the header",
            file=file_path,
            skipped_rows=skipped_rows,
            expected=len(names),
        )


def _as_rows(value: Any) -> Iterator[dict[str, Any]]:
    # A generator, so a line holding a huge array is wrapped into rows a batch at a time.
    if isinstance(value, dict):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield item if isinstance(item, dict) else {"value": item}
    else:
        yield {"value": value}


def iter_jsonl_tables(
    stream: IO[bytes],
    file_path: str = "",
    max_rows: int = JSONL_CHUNK_ROWS,
    max_bytes: int = JSONL_CHUNK_BYTES,
) -> Iterator[pa.Table]:
    rows: list[dict[str, Any]] = []
    pending_bytes = 0
    line_number = 0
    while True:
        line = _read_bounded_line(stream, file_path, "JSON Lines")
        if not line:
            break
        line_number += 1
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except (ValueError, RecursionError) as e:
            raise ObjectStorageError(
                f"{FILE_PARSE_ERROR} '{file_path}' as JSON Lines: line {line_number} isn't valid JSON ({e})."
            ) from e
        pending_bytes += len(line)
        for row in _as_rows(parsed):
            rows.append(row)
            if len(rows) >= max_rows:
                yield table_from_py_list(rows)
                rows = []
                pending_bytes = 0
        if rows and pending_bytes >= max_bytes:
            yield table_from_py_list(rows)
            rows = []
            pending_bytes = 0
    if rows:
        yield table_from_py_list(rows)


def iter_parquet_tables(
    stream: IO[bytes], file_path: str = "", batch_rows: int = PARQUET_BATCH_ROWS
) -> Iterator[pa.Table]:
    try:
        parquet_file = pq.ParquetFile(stream)
        if uses_brotli_compression(parquet_file.metadata):
            raise ObjectStorageError(
                f"{FILE_PARSE_ERROR} '{file_path}' as Parquet: Brotli compression isn't supported. "
                "Write the file with Snappy, Gzip, or Zstd compression instead."
            )
        yielded = False
        for batch in parquet_file.iter_batches(batch_size=batch_rows, use_threads=False):
            if batch.num_rows:
                yielded = True
                yield pa.Table.from_batches([batch])
        if not yielded:
            # A file with no rows still carries a schema, which the pipeline needs to create the table.
            yield parquet_file.schema_arrow.empty_table()
    except pa.ArrowInvalid as e:
        raise ObjectStorageError(f"{FILE_PARSE_ERROR} '{file_path}' as Parquet: {e}") from e


def with_file_columns(table: pa.Table, stored: StoredObject, first_row_number: int = 0) -> pa.Table:
    """Tag every row with the file it came from and its position in that file.

    The position counts the rows the file has yielded so far, so it does not depend on how the file
    was split into chunks.
    """
    for column in (FILE_PATH_COLUMN, FILE_MODIFIED_AT_COLUMN, FILE_ROW_NUMBER_COLUMN):
        if column in table.column_names:
            table = table.drop_columns([column])
    rows = table.num_rows
    table = table.append_column(FILE_PATH_COLUMN, pa.repeat(pa.scalar(stored.path, pa.string()), rows))
    table = table.append_column(
        FILE_MODIFIED_AT_COLUMN,
        pa.repeat(pa.scalar(stored.modified_at, pa.timestamp("us", tz="UTC")), rows),
    )
    return table.append_column(
        FILE_ROW_NUMBER_COLUMN, pa.array(range(first_row_number, first_row_number + rows), pa.int64())
    )


def _iter_gzipped_parquet(stream: IO[bytes], stored: StoredObject) -> Iterator[pa.Table]:
    """Parquet readers seek to the footer, which a gzip stream can't, so the file is unpacked to disk first."""
    with tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES) as unpacked:
        try:
            with gzip.GzipFile(fileobj=stream) as compressed:
                unpacked_bytes = 0
                while chunk := compressed.read(COPY_CHUNK_BYTES):
                    unpacked_bytes += len(chunk)
                    if unpacked_bytes > MAX_UNPACKED_PARQUET_BYTES:
                        raise ObjectStorageError(
                            f"{FILE_PARSE_ERROR} '{stored.path}' as gzip: it unpacks to more than "
                            f"{MAX_UNPACKED_PARQUET_BYTES:,} bytes."
                        )
                    unpacked.write(chunk)
        except (gzip.BadGzipFile, zlib.error, EOFError) as e:
            raise ObjectStorageError(f"{FILE_PARSE_ERROR} '{stored.path}' as gzip: {e}") from e
        unpacked.seek(0)
        yield from iter_parquet_tables(cast(IO[bytes], unpacked), stored.path)


def iter_file_tables(
    stream: IO[bytes],
    stored: StoredObject,
    file_format: FileFormat,
    csv_options: CsvOptions,
    logger: FilteringBoundLogger | None = None,
) -> Iterator[pa.Table]:
    """Read one file as Arrow tables of bounded size, each carrying the `_file_*` columns."""
    if file_format == "parquet":
        if is_compressed(stored.path):
            tables = _iter_gzipped_parquet(stream, stored)
        else:
            tables = iter_parquet_tables(stream, stored.path)
    else:
        binary = cast(IO[bytes], gzip.GzipFile(fileobj=stream)) if is_compressed(stored.path) else stream
        if file_format == "csv":
            delimiter = csv_options.delimiter or ("\t" if stored.path.lower().endswith(TSV_SUFFIXES) else ",")
            tables = iter_csv_tables(binary, csv_options, delimiter, stored.path, logger)
        else:
            tables = iter_jsonl_tables(binary, stored.path)
    rows_read = 0
    try:
        for table in tables:
            yield with_file_columns(table, stored, rows_read)
            rows_read += table.num_rows
    except (gzip.BadGzipFile, zlib.error, EOFError) as e:
        raise ObjectStorageError(f"{FILE_PARSE_ERROR} '{stored.path}' as gzip: {e}") from e
