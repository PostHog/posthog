"""Read-only page slices of on-sandbox result frames (arch doc: the result-store reader).

A kernel node (python/duckdb) writes its result to `/data/results/<result_id>.arrow`;
`/page` requests for it are served here, in the **server** process — a memory-mapped
pyarrow slice that never queues behind a running cell and never touches the data plane
(the node's code is not a HogQL query, so there is nothing to re-query).

Frames live only on the sandbox disk: after a sandbox death the file is gone and the
node has to be re-run. This alive-only trade-off is deliberate.
"""

import os
import uuid
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, BinaryIO

import pyarrow as pa
import pyarrow.parquet as pq

from . import envelope
from .data_plane import _table_to_rows_and_types

_RESULTS_DIR = "/data/results"


@contextmanager
def parquet_result(result_id: str, results_dir: str = _RESULTS_DIR) -> Iterator[BinaryIO]:
    frame_id = uuid.UUID(str(result_id))
    with pa.memory_map(os.path.join(results_dir, f"{frame_id}.arrow")) as source, tempfile.TemporaryFile() as result:
        reader = pa.ipc.open_file(source)
        with pq.ParquetWriter(result, reader.schema) as writer:
            for index in range(reader.num_record_batches):
                batch = reader.get_batch(index)
                if batch.num_rows:
                    writer.write_batch(batch)
        yield result


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
