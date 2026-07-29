"""S3 change buffer for CDC — the ingress side of buffered CDC.

Capture demuxes decoded change events per schema and writes each micro-batch as
one Parquet file under a stable per-schema prefix:

    s3://{DATAWAREHOUSE_BUCKET}/cdc_producer/{team_id}/{schema_id}/{start_seq}-{end_seq}-{file_index}.parquet

The filename carries the batch's position range (`_ph_cdc_seq` min/max) zero-padded
to fixed width so lexicographic order equals numeric order — consumers sort by
filename, never by S3 mtime, and never parse Parquet to establish order.

`file_index` disambiguates batches that share a position range: a micro-flush can
split one transaction (all of whose events share a commit position) across
consecutive batches. Within a capture run the index is strictly increasing per
schema, so (start, end, index) sorts in WAL order. Filenames are deterministic on
replay of the same WAL window, making capture retries idempotent overwrites.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from django.conf import settings

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from structlog.types import FilteringBoundLogger

from products.data_warehouse.backend.facade.api import get_s3_client
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_SEQ_COLUMN
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.common import (
    ensure_bucket,
    strip_s3_protocol,
)

BUFFER_ROOT_FOLDER = "cdc_producer"

_SEQ_WIDTH = 20  # zero-pad width covering the full u64 range
_INDEX_WIDTH = 6


def get_buffer_prefix(team_id: int, schema_id: str) -> str:
    return f"s3://{settings.DATAWAREHOUSE_BUCKET}/{BUFFER_ROOT_FOLDER}/{team_id}/{schema_id}"


def build_buffer_file_name(start_seq: int, end_seq: int, file_index: int) -> str:
    return f"{start_seq:0{_SEQ_WIDTH}d}-{end_seq:0{_SEQ_WIDTH}d}-{file_index:0{_INDEX_WIDTH}d}.parquet"


def parse_buffer_file_name(file_name: str) -> tuple[int, int, int] | None:
    """Parse `{start}-{end}-{index}.parquet` → (start_seq, end_seq, file_index).

    Returns None for names that don't match the contract (foreign files are
    ignored, never treated as buffer data).
    """
    if not file_name.endswith(".parquet"):
        return None
    parts = file_name.removesuffix(".parquet").split("-")
    if len(parts) != 3:
        return None
    try:
        start_seq, end_seq, file_index = (int(part) for part in parts)
    except ValueError:
        return None
    if len(parts[0]) != _SEQ_WIDTH or len(parts[1]) != _SEQ_WIDTH or len(parts[2]) != _INDEX_WIDTH:
        return None
    return start_seq, end_seq, file_index


@dataclass(frozen=True, slots=True)
class BufferFileWriteResult:
    s3_path: str
    row_count: int
    start_seq: int
    end_seq: int
    file_index: int
    write_duration_seconds: float


class CDCBufferWriter:
    """Writes per-schema change batches to the S3 buffer.

    The table must carry `_ph_cdc_seq` (engine-neutral monotonic position per row);
    the file's position range is derived from it.
    """

    def __init__(self, logger: FilteringBoundLogger) -> None:
        self._logger = logger
        self._s3 = get_s3_client()
        ensure_bucket()

    def write_batch(
        self,
        *,
        team_id: int,
        schema_id: str,
        table: pa.Table,
        file_index: int,
    ) -> BufferFileWriteResult:
        if CDC_SEQ_COLUMN not in table.column_names:
            raise ValueError(f"Buffer batches must carry {CDC_SEQ_COLUMN}")
        if table.num_rows == 0:
            raise ValueError("Refusing to write an empty buffer file")

        min_max = pc.min_max(table.column(CDC_SEQ_COLUMN))
        start_seq = min_max["min"].as_py()
        end_seq = min_max["max"].as_py()
        if start_seq is None or end_seq is None:
            raise ValueError(f"{CDC_SEQ_COLUMN} must be non-null in buffer batches")

        file_name = build_buffer_file_name(start_seq, end_seq, file_index)
        s3_path = f"{get_buffer_prefix(team_id, schema_id)}/{file_name}"

        write_start = time.perf_counter()
        with self._s3.open(strip_s3_protocol(s3_path), "wb") as f:
            pq.write_table(table, f, compression="zstd")
        write_duration = time.perf_counter() - write_start

        self._logger.debug(
            "cdc_buffer_file_written",
            s3_path=s3_path,
            row_count=table.num_rows,
            start_seq=start_seq,
            end_seq=end_seq,
            file_index=file_index,
        )

        return BufferFileWriteResult(
            s3_path=s3_path,
            row_count=table.num_rows,
            start_seq=start_seq,
            end_seq=end_seq,
            file_index=file_index,
            write_duration_seconds=write_duration,
        )
