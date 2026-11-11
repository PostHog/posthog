import threading
from collections.abc import Callable
from typing import Any

import pyarrow as pa
import structlog
import pyarrow.compute as pc
import pyarrow.parquet as pq

from products.data_warehouse.backend.facade.api import get_s3_client
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.common import strip_s3_protocol

logger = structlog.get_logger(__name__)

# One synchronous client for every read this process makes. A sync `S3FileSystem` runs its I/O on
# fsspec's own long-lived loop thread, so it is safe to share across the loader's worker threads and
# across the short-lived event loops `async_to_sync` spins up. Building one costs an aiobotocore
# client and credential resolution, which is why it is not rebuilt per batch.
_shared_lock = threading.Lock()
_shared_s3: Any = None


def _get_shared_s3() -> Any:
    global _shared_s3
    s3 = _shared_s3
    if s3 is None:
        with _shared_lock:
            if _shared_s3 is None:
                _shared_s3 = get_s3_client(skip_instance_cache=True)
            s3 = _shared_s3
    return s3


def _discard_shared_s3(s3: Any) -> None:
    global _shared_s3
    with _shared_lock:
        if _shared_s3 is s3:
            _shared_s3 = None


def _read_table(s3: Any, path: str) -> pa.Table:
    with s3.open(path, "rb") as f:
        return pq.read_table(f)


def _first_non_null(column: pa.ChunkedArray) -> Any:
    for chunk in column.chunks:
        if chunk.null_count == len(chunk):
            continue
        index = pc.index(chunk.is_valid(), True).as_py()
        if index != -1:
            return chunk[index].as_py()
    return None


def _all_null_columns(row_group: pq.RowGroupMetaData) -> set[str]:
    """Top-level columns that the row group statistics show as null in each row."""
    all_null: set[str] = set()
    seen: set[str] = set()
    for index in range(row_group.num_columns):
        column = row_group.column(index)
        path = column.path_in_schema
        if path in seen:
            # A nested leaf can share a dotted path with a top-level column. Read both.
            all_null.discard(path)
            continue
        seen.add(path)
        statistics = column.statistics
        if statistics is not None and statistics.null_count == row_group.num_rows:
            all_null.add(path)
    return all_null


def _read_first_values(s3: Any, path: str) -> pa.Table:
    with s3.open(path, "rb") as f:
        parquet_file = pq.ParquetFile(f)
        schema = parquet_file.schema_arrow
        pending = [field.name for field in schema if pa.types.is_string(field.type)]
        first_values: dict[str, Any] = {}
        for index in range(parquet_file.num_row_groups):
            if not pending:
                break
            all_null = _all_null_columns(parquet_file.metadata.row_group(index))
            columns = [name for name in pending if name not in all_null]
            if not columns:
                continue
            row_group = parquet_file.read_row_group(index, columns=columns)
            for name in columns:
                value = _first_non_null(row_group.column(name))
                if value is not None:
                    first_values[name] = value
                    pending.remove(name)
    return pa.table(
        [
            pa.array([first_values[field.name]], type=field.type)
            if field.name in first_values
            else pa.nulls(1, type=field.type)
            for field in schema
        ],
        schema=schema,
    )


def _with_shared_s3(read: Callable[[Any, str], pa.Table], s3_path: str) -> pa.Table:
    s3_path_without_protocol = strip_s3_protocol(s3_path)
    s3 = _get_shared_s3()
    try:
        return read(s3, s3_path_without_protocol)
    except RuntimeError as e:
        # The RuntimeError s3fs raises here is a session whose event loop is gone. A fresh client is
        # the fix, and a single retry keeps a genuine fault from looping.
        if "loop" not in str(e).lower():
            raise
        logger.warning("parquet_read_client_rebuilt", s3_path=s3_path, error=str(e))
        _discard_shared_s3(s3)
        return read(_get_shared_s3(), s3_path_without_protocol)


def read_parquet(s3_path: str) -> pa.Table:
    logger.debug("reading_parquet", s3_path=s3_path)

    table = _with_shared_s3(_read_table, s3_path)

    logger.debug("parquet_read_success", s3_path=s3_path, row_count=table.num_rows)

    return table


def read_parquet_first_values(s3_path: str) -> pa.Table:
    """One row with the file's schema: the first non-null value of each string column, null elsewhere.

    For a caller that only needs to tell a JSON string column from a plain one, which is decided by
    the first non-null value. Reads the footer, then the string columns of each row group until each
    has a value, and skips a column chunk that the statistics show as all null. The rows of the file
    are not loaded.
    """
    logger.debug("reading_parquet_first_values", s3_path=s3_path)

    return _with_shared_s3(_read_first_values, s3_path)


def list_parquet_files(data_folder: str) -> list[str]:
    s3 = _get_shared_s3()
    folder_without_protocol = strip_s3_protocol(data_folder)

    try:
        files = s3.ls(folder_without_protocol)
        parquet_files = [f"s3://{f}" for f in files if f.endswith(".parquet")]
        parquet_files.sort()

        logger.debug("list_parquet_files", data_folder=data_folder, file_count=len(parquet_files))

        return parquet_files
    except FileNotFoundError:
        logger.debug("data_folder_not_found", data_folder=data_folder)
        return []
