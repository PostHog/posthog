import threading
from typing import Any

import pyarrow as pa
import structlog
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


def read_parquet(s3_path: str) -> pa.Table:
    s3_path_without_protocol = strip_s3_protocol(s3_path)

    logger.debug("reading_parquet", s3_path=s3_path)

    s3 = _get_shared_s3()
    try:
        table = _read_table(s3, s3_path_without_protocol)
    except RuntimeError as e:
        # The RuntimeError s3fs raises here is a session whose event loop is gone. A fresh client is
        # the fix, and a single retry keeps a genuine fault from looping.
        if "loop" not in str(e).lower():
            raise
        logger.warning("parquet_read_client_rebuilt", s3_path=s3_path, error=str(e))
        _discard_shared_s3(s3)
        table = _read_table(_get_shared_s3(), s3_path_without_protocol)

    logger.debug("parquet_read_success", s3_path=s3_path, row_count=table.num_rows)

    return table


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
