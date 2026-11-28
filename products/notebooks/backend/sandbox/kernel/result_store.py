"""Read-only page slices of on-sandbox result frames (arch doc: the result-store reader).

A kernel node (python/duckdb) writes its result to `/data/results/<result_id>.arrow`;
`/page` requests for it are served here, in the **server** process — a memory-mapped
pyarrow slice that never queues behind a running cell and never touches the data plane
(the node's code is not a HogQL query, so there is nothing to re-query).

Frames live only on the sandbox disk: after a sandbox death the file is gone and the
node has to be re-run. This alive-only trade-off is deliberate.
"""

import io
import os
import time
import uuid
import shutil
import tempfile
from collections.abc import Buffer, Iterator
from contextlib import contextmanager
from typing import Any, BinaryIO

import pyarrow as pa
import pyarrow.parquet as pq

from . import envelope
from .data_plane import _table_to_rows_and_types

_RESULTS_DIR = "/data/results"


class ModelOutputTooLarge(ValueError):
    pass


class _BoundedParquetFile(io.RawIOBase):
    def __init__(self, file: BinaryIO, limit: int):
        super().__init__()
        self.file = file
        self.limit = limit

    def writable(self) -> bool:
        return True

    def write(self, data: Buffer) -> int:
        if self.file.tell() + memoryview(data).nbytes > self.limit:
            raise ModelOutputTooLarge("The notebook output exceeds the warehouse file size limit.")
        return self.file.write(data)

    def tell(self) -> int:
        return self.file.tell()


@contextmanager
def parquet_result(result_id: str, results_dir: str, *, max_rows: int, max_bytes: int) -> Iterator[BinaryIO]:
    frame_id = uuid.UUID(str(result_id))
    with pa.memory_map(os.path.join(results_dir, f"{frame_id}.arrow")) as source, tempfile.TemporaryFile() as result:
        if source.size() > 4 * max_bytes:
            raise ModelOutputTooLarge("The notebook frame exceeds the warehouse size limit.")
        reader = pa.ipc.open_file(source)
        rows = 0
        with (
            pa.PythonFile(_BoundedParquetFile(result, max_bytes), mode="w") as sink,
            pq.ParquetWriter(sink, reader.schema) as writer,
        ):
            for index in range(reader.num_record_batches):
                batch = reader.get_batch(index)
                rows += batch.num_rows
                if rows > max_rows:
                    raise ModelOutputTooLarge("The notebook output exceeds the warehouse model row limit.")
                if batch.num_rows:
                    writer.write_batch(batch)
        yield result


def retire_model_session(directory: str) -> None:
    if not os.path.isdir(directory) or os.path.islink(directory):
        return
    for name in ("frames", "duck", "runs"):
        path = os.path.join(directory, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
    # Publication and its retries may still read the retired kernel's result files.
    os.utime(directory)
    cutoff = time.time() - 2 * 60 * 60
    with os.scandir(os.path.dirname(directory)) as sessions:
        for old in sessions:
            if old.is_dir(follow_symlinks=False) and old.stat(follow_symlinks=False).st_mtime < cutoff:
                shutil.rmtree(old.path)


def model_directory(session: str) -> str:
    return os.path.join("/data/model-runs", str(uuid.UUID(str(session))))


class ResultStoreError(Exception):
    """A page request the result store can't serve; message is user-facing."""


def read_page(result_id: str, offset: int, limit: int, results_dir: str = _RESULTS_DIR) -> dict[str, Any]:
    """Slice one page out of a stored result frame; raises ResultStoreError when it can't."""
    try:
        frame_id = str(uuid.UUID(result_id))  # also confines the path join to a UUID filename
    except (TypeError, ValueError):
        raise ResultStoreError("Invalid result id.")
    path = os.path.join(results_dir, f"{frame_id}.arrow")
    if not os.path.exists(path):
        raise ResultStoreError("This result is no longer in the sandbox — re-run the node.")
    try:
        with pa.memory_map(path) as source:
            table = pa.ipc.open_file(source).read_all()
    except pa.ArrowInvalid as exc:
        raise ResultStoreError(f"Stored result frame is unreadable: {exc}")
    columns, rows, types = _table_to_rows_and_types(table.slice(offset, limit))
    return {
        "columns": columns,
        "types": types,
        "rows": envelope.json_safe_rows(rows),
        "has_more": offset + limit < table.num_rows,
    }
