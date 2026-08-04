"""Read-only page slices of on-sandbox result frames (arch doc: the result-store reader).

A kernel node (python/duckdb) writes its result to `/data/results/<result_id>.arrow`;
`/page` requests for it are served here, in the **server** process — a memory-mapped
pyarrow slice that never queues behind a running cell and never touches the data plane
(the node's code is not a HogQL query, so there is nothing to re-query).

Frames live only on the sandbox disk: after a sandbox death the file is gone and the
node has to be re-run — the documented alive-only trade-off in sql_v2_result_delivery.md.
"""

import os
import uuid
from typing import Any

import pyarrow as pa

from . import envelope
from .data_plane import _table_to_rows_and_types

_RESULTS_DIR = "/data/results"


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
