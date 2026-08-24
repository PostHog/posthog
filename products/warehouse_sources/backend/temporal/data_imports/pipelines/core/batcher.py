import sys
from collections import deque
from typing import Any, Optional

import pyarrow as pa
import pyarrow.compute as pc
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    BinaryColumnReporter,
    table_from_py_list,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.table_stats import (
    record_table_stats,
    table_payload_bytes,
)
from products.warehouse_sources.backend.temporal.data_imports.workload_report import report_buffer_bytes, report_phase

DEFAULT_CHUNK_SIZE_BYTES: int = 200 * 1024 * 1024  # 200 MiB
DEFAULT_CHUNK_SIZE: int = 500_000

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


def _split_table(table: pa.Table, *, offset_limit: int, bytes_limit: int) -> list[pa.Table]:
    """Row-halve `table` (zero-copy slices) until every slice is under both the per-column offset limit
    and the total-bytes limit. `num_rows <= 1` is the base case, so a lone oversized row is yielded as-is."""
    if table.num_rows <= 1:
        return [table]
    if _max_offset_pressure(table) <= offset_limit and table_payload_bytes(table) <= bytes_limit:
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
    _table_buffer: list[pa.Table]
    _table_buffer_rows: int
    _table_buffer_bytes: int
    _table_buffer_schema: Optional[pa.Schema]
    _ready_bytes: int
    _coalesce_tables: bool
    _ready: deque[pa.Table]
    _logger: FilteringBoundLogger
    _chunk_size: int
    _chunk_size_bytes: int
    _max_column_offset_bytes: int
    _max_table_bytes: int
    _source_type: Optional[str]
    _team_id: Optional[int]
    _schema_name: Optional[str]
    _primary_keys: Optional[list[str]]
    _binary_reporter: BinaryColumnReporter

    def __init__(
        self,
        logger: FilteringBoundLogger,
        chunk_size: Optional[int] = None,
        chunk_size_bytes: Optional[int] = None,
        max_column_offset_bytes: Optional[int] = None,
        max_table_bytes: Optional[int] = None,
        source_type: Optional[str] = None,
        team_id: Optional[int] = None,
        schema_name: Optional[str] = None,
        coalesce_tables: bool = False,
        primary_keys: Optional[list[str]] = None,
    ) -> None:
        self._logger = logger
        self._primary_keys = primary_keys
        self._binary_reporter = BinaryColumnReporter(logger)

        self._chunk_size = chunk_size or DEFAULT_CHUNK_SIZE
        self._chunk_size_bytes = chunk_size_bytes or DEFAULT_CHUNK_SIZE_BYTES
        self._max_column_offset_bytes = max_column_offset_bytes or DEFAULT_MAX_COLUMN_OFFSET_BYTES
        self._max_table_bytes = max_table_bytes or DEFAULT_MAX_TABLE_BYTES
        # When set, each materialised table is measured under `stage="batcher"`. Left None by
        # source-internal batchers (e.g. apify), whose output is measured when it reaches the
        # pipeline's own batcher — so this only records once, with the real source_type.
        self._source_type = source_type
        self._team_id = team_id
        self._schema_name = schema_name
        # Off by default because coalescing delays when a yielded table becomes a durable batch:
        # sources that checkpoint resume state or delete upstream staging right after yielding
        # (ResumableSource implementations, the webhook S3 path) rely on yield => persisted and
        # would lose data across a crash if their tables sat in this buffer. Only enable for
        # sources with no such dependency.
        self._coalesce_tables = coalesce_tables

        self._buffer = []
        self._buffer_size_bytes = 0
        self._table_buffer = []
        self._table_buffer_rows = 0
        self._table_buffer_bytes = 0
        self._table_buffer_schema = None
        self._ready = deque()
        self._ready_bytes = 0

    def _rows_to_table(self, rows: list[Any]) -> pa.Table:
        return table_from_py_list(rows, primary_keys=self._primary_keys, binary_reporter=self._binary_reporter)

    def _set_ready(self, table: pa.Table) -> None:
        """Split `table` so no yielded chunk overflows a 32-bit offset column or exceeds
        the per-table Arrow-payload cap (keeping the loader's per-batch merge bounded)."""
        chunks = _split_table(table, offset_limit=self._max_column_offset_bytes, bytes_limit=self._max_table_bytes)
        payload_bytes = table_payload_bytes(table)
        # The materialised table is this activity's true in-memory peak, already sized here for
        # chunking — feed the same number to the workload self-report at zero extra cost. Phase is
        # re-declared here because v2 interleaves extract and merge per chunk: without flipping back,
        # the writer's "merge" would latch after the first chunk and every later mid-extract death
        # would be misreported as a merge death, biasing the exact distribution this signal exists
        # to measure.
        report_phase("extract")
        # Held until `get_table` drains every chunk, so it stays part of what this activity occupies.
        self._ready_bytes = payload_bytes
        report_buffer_bytes(payload_bytes)
        if self._source_type is not None:
            # The materialised table is the true in-memory peak (an unbounded source yields one giant
            # list -> one giant table here, before the split into bounded chunks). With table
            # coalescing this is the whole coalesced batch, not one source yield; the buffered input
            # tables it was concatenated from share its buffers, so it still measures the real peak.
            record_table_stats(
                source_type=self._source_type,
                stage="batcher",
                num_rows=table.num_rows,
                payload_bytes=payload_bytes,
                logger=self._logger,
                team_id=self._team_id,
                schema_name=self._schema_name,
            )
        if len(chunks) > 1 and payload_bytes > self._max_table_bytes:
            self._logger.info(
                "batcher_split_by_bytes",
                payload_bytes=payload_bytes,
                bytes_limit=self._max_table_bytes,
                chunk_count=len(chunks),
                row_count=table.num_rows,
            )
        self._ready = deque(chunks)

    def _batch_table(self, table: pa.Table) -> None:
        """Buffer `table` and flush the accumulated buffer once `_chunk_size` / `_chunk_size_bytes`
        is reached, so a source's per-yield fetch size doesn't dictate batch granularity (a driver
        fetching 10k rows per Arrow table would otherwise emit one queue batch per fetch).

        Bytes are counted as each table arrives, and a table that would push the buffer past
        `_chunk_size_bytes` flushes the buffer *before* joining it, so buffered payload never
        exceeds the byte cap unless a single table does on its own. With the default caps
        (200 MiB chunk vs 256 MiB max table) the flushed batch stays under `_max_table_bytes`,
        so `_split_table` doesn't undo the coalescing, and accumulation memory stays bounded on
        pods where memory is the constraint.
        """
        table_bytes = table_payload_bytes(table)

        if not self._table_buffer:
            self._start_table_buffer(table, table_bytes)
            self._flush_table_buffer_if_full()
            return

        unified_schema = self._unify_schema_or_none(table.schema)
        would_overflow = (
            self._table_buffer_rows + table.num_rows > self._chunk_size
            or self._table_buffer_bytes + table_bytes > self._chunk_size_bytes
        )
        if unified_schema is None or would_overflow:
            if unified_schema is None:
                self._logger.info(
                    "batcher_flush_on_schema_drift",
                    buffered_rows=self._table_buffer_rows,
                    incoming_rows=table.num_rows,
                )
            # `_set_ready` replaces `_ready` wholesale, so only one flush can happen per
            # `batch()` call; the incoming table waits in a fresh buffer until the next
            # call (or `get_table` at end of stream) flushes it.
            self._flush_table_buffer()
            self._start_table_buffer(table, table_bytes)
            return

        self._table_buffer.append(table)
        self._table_buffer_rows += table.num_rows
        self._table_buffer_bytes += table_bytes
        self._table_buffer_schema = unified_schema
        self._flush_table_buffer_if_full()

    def _unify_schema_or_none(self, schema: pa.Schema) -> Optional[pa.Schema]:
        """Permissively unify `schema` with the buffered schema, or None if they can't be merged.

        Permissive promotion (nullability, new columns, numeric widening) matches how
        `S3BatchWriter.write_batch` already unifies schemas across batches, so coalescing doesn't
        reject drift the writer would have accepted. Non-promotable drift (e.g. int64 vs string)
        returns None and the caller flushes, yielding the same per-table failure surface the
        writer had.
        """
        assert self._table_buffer_schema is not None
        try:
            return pa.unify_schemas([self._table_buffer_schema, schema], promote_options="permissive")
        except (pa.ArrowInvalid, pa.ArrowTypeError):
            return None

    def _start_table_buffer(self, table: pa.Table, table_bytes: int) -> None:
        self._table_buffer = [table]
        self._table_buffer_rows = table.num_rows
        self._table_buffer_bytes = table_bytes
        self._table_buffer_schema = table.schema

    def _flush_table_buffer_if_full(self) -> None:
        if self._table_buffer_rows >= self._chunk_size or self._table_buffer_bytes >= self._chunk_size_bytes:
            self._flush_table_buffer()

    def _flush_table_buffer(self) -> None:
        if len(self._table_buffer) == 1:
            table = self._table_buffer[0]
        else:
            # Zero-copy for matching schemas (the output table references the buffered chunks);
            # only columns needing promotion are cast, so the flush doesn't double peak memory
            # in the common no-drift case.
            table = pa.concat_tables(self._table_buffer, promote_options="permissive")
        self._table_buffer = []
        self._table_buffer_rows = 0
        self._table_buffer_bytes = 0
        self._table_buffer_schema = None
        self._set_ready(table)

    def _estimate_size(self, obj: Any) -> int:
        if isinstance(obj, dict):
            return sys.getsizeof(obj) + sum(self._estimate_size(k) + self._estimate_size(v) for k, v in obj.items())
        elif isinstance(obj, list | tuple | set):
            return sys.getsizeof(obj) + sum(self._estimate_size(i) for i in obj)
        else:
            return sys.getsizeof(obj)

    def batch(self, item: list[Any] | dict | pa.Table) -> None:
        self._batch(item)
        # Report after every item, not only when a chunk completes. `_set_ready` fires once a chunk
        # is materialised, so an activity accumulating toward one reported whatever the *previous*
        # chunk measured — a long accumulation looked like it held nothing, and a death inside it
        # was attributed to a co-tenant. The phase is re-declared for the same reason `_set_ready`
        # does it: without it a death mid-accumulation reads as a merge death.
        report_phase("extract")
        report_buffer_bytes(self._ready_bytes + self._table_buffer_bytes + self._buffer_size_bytes)

    def _batch(self, item: list[Any] | dict | pa.Table) -> None:
        if self._ready:
            raise Exception("Batcher already has a table ready to yield. Call get_table() before batching more items.")

        # Mirror of the pa.Table guard below: buffered tables and buffered rows can't be merged
        # into one batch, so mixing them would silently reorder or drop data on flush.
        if self._table_buffer and not isinstance(item, pa.Table):
            raise Exception("Cannot batch list/dict rows while pa.Tables are buffered; call get_table() first")

        if isinstance(item, list):
            if len(self._buffer) > 0:
                self._buffer.extend(item)
                self._buffer_size_bytes += self._estimate_size(item)
                if self._buffer_size_bytes >= self._chunk_size_bytes or len(self._buffer) >= self._chunk_size:
                    self._logger.debug(f"Processing buffer (list). Length of buffer = {len(self._buffer)}")

                    self._set_ready(self._rows_to_table(self._buffer))
                else:
                    return
            else:
                self._buffer_size_bytes += self._estimate_size(item)
                if self._buffer_size_bytes >= self._chunk_size_bytes or len(item) >= self._chunk_size:
                    self._logger.debug(f"Processing item (list). Length of item = {len(item)}")
                    self._set_ready(self._rows_to_table(item))
                else:
                    self._buffer.extend(item)
                    return
        elif isinstance(item, dict):
            self._buffer.append(item)
            self._buffer_size_bytes += self._estimate_size(item)
            if self._buffer_size_bytes < self._chunk_size_bytes and len(self._buffer) < self._chunk_size:
                return

            self._logger.debug(f"Processing buffer (dict). Length of buffer = {len(self._buffer)}")
            self._set_ready(self._rows_to_table(self._buffer))
        elif isinstance(item, pa.Table):
            # A pa.Table never joins the list/dict buffer. Clearing the buffer
            # below would silently drop any rows accumulated from earlier list/dict
            # items, so treat a non-empty buffer here as a programming error rather than
            # losing data. (In practice sources emit only one item type, never a mix.)
            if self._buffer:
                raise Exception("Cannot batch a pa.Table while list/dict rows are buffered; call get_table() first")
            if self._coalesce_tables:
                self._batch_table(item)
                return
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
            return len(self._ready) > 0 or len(self._buffer) > 0 or len(self._table_buffer) > 0

        return len(self._ready) > 0

    def get_table(self) -> pa.Table:
        if not self._ready and len(self._buffer) > 0:
            self._logger.debug(f"Processing leftover buffer. Length of buffer = {len(self._buffer)}")
            self._set_ready(self._rows_to_table(self._buffer))
            self._buffer = []
            self._buffer_size_bytes = 0

        # End-of-stream flush of a partial Arrow buffer, matching the list/dict path above;
        # dropping it would lose every row batched since the last full chunk.
        if not self._ready and len(self._table_buffer) > 0:
            self._logger.debug(f"Processing leftover table buffer. Buffered tables = {len(self._table_buffer)}")
            self._flush_table_buffer()

        if self._ready:
            chunk = self._ready.popleft()
            if not self._ready:
                self._ready_bytes = 0
            return chunk

        raise Exception("No chunks available to yield")
