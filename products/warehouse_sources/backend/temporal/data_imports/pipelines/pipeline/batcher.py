import sys
from collections import deque
from typing import Any, Optional

import pyarrow as pa
import pyarrow.compute as pc
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list

DEFAULT_CHUNK_SIZE_BYTES: int = 200 * 1024 * 1024  # 200 MiB
DEFAULT_CHUNK_SIZE: int = 5000

# string/binary/list use 32-bit offsets and overflow ("Offset overflow error") once a column's
# offsets cross 2^31 (~2.1 GB); delta-rs hits this when it concatenates merge-source chunks.
DEFAULT_MAX_COLUMN_OFFSET_BYTES: int = 1_500_000_000  # ~1.4 GiB, safely under the 2 GB (2^31) limit

# Cap each yielded table's real Arrow payload: wide rows / large cells can materialize a multi-GiB
# table from a few thousand rows, which becomes the loader's per-batch merge memory and OOMs the pod.
DEFAULT_MAX_TABLE_BYTES: int = 256 * 1024 * 1024  # 256 MiB of Arrow payload


def _column_offset_pressure(col: pa.ChunkedArray) -> int:
    """32-bit-offset pressure: value bytes (string/binary) or child element count (list); 0 otherwise.

    Slice-accurate via `pc.sum` over per-row lengths (not `Array.nbytes`, which reports the full
    shared buffer for a zero-copy slice and would break the recursive split).
    """
    col_type = col.type
    if pa.types.is_string(col_type) or pa.types.is_binary(col_type):
        total = pc.sum(pc.binary_length(col)).as_py()
        return int(total or 0)
    if pa.types.is_list(col_type):
        total = pc.sum(pc.list_value_length(col)).as_py()
        return int(total or 0)
    return 0


def _max_offset_pressure(table: pa.Table) -> int:
    return max((_column_offset_pressure(table.column(name)) for name in table.column_names), default=0)


def _column_payload_bytes(col: pa.ChunkedArray) -> int:
    """Slice-accurate in-memory payload bytes: value bytes + offset buffer (string/binary/list)
    or col_length * byte_width (fixed-width); nested/other types return 0. Avoids `.nbytes` (wrong for slices)."""
    col_type = col.type
    col_length = len(col)
    if pa.types.is_string(col_type) or pa.types.is_binary(col_type):
        payload = int(pc.sum(pc.binary_length(col)).as_py() or 0)
        return payload + col_length * 4  # value bytes + 32-bit offsets
    if pa.types.is_large_string(col_type) or pa.types.is_large_binary(col_type):
        # 64-bit offsets can't overflow (the offset guard skips them) but still hold real payload.
        payload = int(pc.sum(pc.binary_length(col)).as_py() or 0)
        return payload + col_length * 8
    if pa.types.is_list(col_type):
        elements = int(pc.sum(pc.list_value_length(col)).as_py() or 0)
        return elements + col_length * 4
    if pa.types.is_struct(col_type):
        # Recurse into child fields so a nested struct (e.g. a Mongo document carried under `data`) is
        # counted instead of undercounting to 0 — otherwise the per-table byte split never sees the
        # payload that actually drives the merge's memory. `flatten()` yields one ChunkedArray per field.
        # Guarded like the fixed-width branch below: an unexpected flatten failure degrades to 0 rather
        # than propagating and breaking size accounting for the whole table.
        try:
            return sum(_column_payload_bytes(child) for child in col.flatten())
        except Exception:
            return 0
    # Fixed-width primitives expose bit_width; variable-length / other nested types raise -> 0.
    # Known limitation: map and sub-byte bool columns still undercount to 0 (we bound large string/JSON
    # and struct payloads, the actual OOM drivers).
    try:
        bit_width = col_type.bit_width
    except (ValueError, AttributeError):
        return 0
    return col_length * (bit_width // 8)


def _table_payload_bytes(table: pa.Table) -> int:
    return sum(_column_payload_bytes(table.column(name)) for name in table.column_names)


def _split_table(table: pa.Table, *, offset_limit: int, bytes_limit: int) -> list[pa.Table]:
    """Row-halve `table` (zero-copy slices) until every slice is under both the per-column offset limit
    and the total-bytes limit. `num_rows <= 1` is the base case, so a lone oversized row is yielded as-is."""
    if table.num_rows <= 1:
        return [table]
    if _max_offset_pressure(table) <= offset_limit and _table_payload_bytes(table) <= bytes_limit:
        return [table]

    mid = table.num_rows // 2
    left = table.slice(0, mid)
    right = table.slice(mid, table.num_rows - mid)
    return _split_table(left, offset_limit=offset_limit, bytes_limit=bytes_limit) + _split_table(
        right, offset_limit=offset_limit, bytes_limit=bytes_limit
    )


class Batcher:
    _buffer: list[Any]
    _buffer_size_bytes: int
    _ready: deque[pa.Table]
    _logger: FilteringBoundLogger
    _chunk_size: int
    _chunk_size_bytes: int
    _max_column_offset_bytes: int
    _max_table_bytes: int

    def __init__(
        self,
        logger: FilteringBoundLogger,
        chunk_size: Optional[int] = None,
        chunk_size_bytes: Optional[int] = None,
        max_column_offset_bytes: Optional[int] = None,
        max_table_bytes: Optional[int] = None,
    ) -> None:
        self._logger = logger

        self._chunk_size = chunk_size or DEFAULT_CHUNK_SIZE
        self._chunk_size_bytes = chunk_size_bytes or DEFAULT_CHUNK_SIZE_BYTES
        self._max_column_offset_bytes = max_column_offset_bytes or DEFAULT_MAX_COLUMN_OFFSET_BYTES
        self._max_table_bytes = max_table_bytes or DEFAULT_MAX_TABLE_BYTES

        self._buffer = []
        self._buffer_size_bytes = 0
        self._ready = deque()

    def _set_ready(self, table: pa.Table) -> None:
        """Split `table` so no yielded chunk overflows a 32-bit offset column or exceeds
        the per-table Arrow-payload cap (keeping the loader's per-batch merge bounded)."""
        chunks = _split_table(table, offset_limit=self._max_column_offset_bytes, bytes_limit=self._max_table_bytes)
        if len(chunks) > 1:
            payload_bytes = _table_payload_bytes(table)
            if payload_bytes > self._max_table_bytes:
                self._logger.info(
                    "batcher_split_by_bytes",
                    payload_bytes=payload_bytes,
                    bytes_limit=self._max_table_bytes,
                    chunk_count=len(chunks),
                    row_count=table.num_rows,
                )
        self._ready = deque(chunks)

    def _estimate_size(self, obj: Any) -> int:
        if isinstance(obj, dict):
            return sys.getsizeof(obj) + sum(self._estimate_size(k) + self._estimate_size(v) for k, v in obj.items())
        elif isinstance(obj, list | tuple | set):
            return sys.getsizeof(obj) + sum(self._estimate_size(i) for i in obj)
        else:
            return sys.getsizeof(obj)

    def batch(self, item: list[Any] | dict | pa.Table) -> None:
        if self._ready:
            raise Exception("Batcher already has a table ready to yield. Call get_table() before batching more items.")

        if isinstance(item, list):
            if len(self._buffer) > 0:
                self._buffer.extend(item)
                self._buffer_size_bytes += self._estimate_size(item)
                if self._buffer_size_bytes >= self._chunk_size_bytes or len(self._buffer) >= self._chunk_size:
                    self._logger.debug(f"Processing buffer (list). Length of buffer = {len(self._buffer)}")

                    self._set_ready(table_from_py_list(self._buffer))
                else:
                    return
            else:
                self._buffer_size_bytes += self._estimate_size(item)
                if self._buffer_size_bytes >= self._chunk_size_bytes or len(item) >= self._chunk_size:
                    self._logger.debug(f"Processing item (list). Length of item = {len(item)}")
                    self._set_ready(table_from_py_list(item))
                else:
                    self._buffer.extend(item)
                    return
        elif isinstance(item, dict):
            self._buffer.append(item)
            self._buffer_size_bytes += self._estimate_size(item)
            if self._buffer_size_bytes < self._chunk_size_bytes and len(self._buffer) < self._chunk_size:
                return

            self._logger.debug(f"Processing buffer (dict). Length of buffer = {len(self._buffer)}")
            self._set_ready(table_from_py_list(self._buffer))
        elif isinstance(item, pa.Table):
            # A pa.Table is self-contained and bypasses the buffer. Clearing the buffer
            # below would silently drop any rows accumulated from earlier list/dict
            # items, so treat a non-empty buffer here as a programming error rather than
            # losing data. (In practice sources emit only one item type, never a mix.)
            if self._buffer:
                raise Exception("Cannot batch a pa.Table while list/dict rows are buffered; call get_table() first")
            self._set_ready(item)
        else:
            raise Exception(f"Unhandled item type: {item.__class__.__name__}")

        # The list/dict branches above materialized the buffer into `_ready`, and the
        # pa.Table branch is guaranteed empty by the guard — so the buffer is now spent.
        # Reset it (and its byte counter) so the next batching cycle starts fresh.
        self._buffer = []
        self._buffer_size_bytes = 0

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        if include_incomplete_chunk:
            return len(self._ready) > 0 or len(self._buffer) > 0

        return len(self._ready) > 0

    def get_table(self) -> pa.Table:
        if not self._ready and len(self._buffer) > 0:
            self._logger.debug(f"Processing leftover buffer. Length of buffer = {len(self._buffer)}")
            self._set_ready(table_from_py_list(self._buffer))
            self._buffer = []
            self._buffer_size_bytes = 0

        if self._ready:
            return self._ready.popleft()

        raise Exception("No chunks available to yield")
