"""Reading a staged parquet batch as a stream of record batches.

Row groups are read one at a time rather than the whole file at once. A staged batch targets
around 200 MiB of Arrow payload, so materializing it per destination would multiply that by
the number of destinations a run fans out to.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pyarrow as pa
import pyarrow.parquet as pq
from asgiref.sync import sync_to_async

from products.data_warehouse.backend.facade.api import get_s3_client
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.common import strip_s3_protocol

# Rows per record batch handed to a writer. Small enough that a writer buffering one batch
# stays bounded, large enough that per-batch overhead stays negligible.
DEFAULT_BATCH_ROWS = 50_000


def read_parquet_schema(s3_path: str) -> pa.Schema:
    """The Arrow schema of a staged file, read from its footer without scanning any rows."""
    s3 = get_s3_client()
    with s3.open(strip_s3_protocol(s3_path), "rb") as f:
        return pq.ParquetFile(f).schema_arrow


def iter_record_batches(s3_path: str, batch_rows: int = DEFAULT_BATCH_ROWS) -> Iterator[pa.RecordBatch]:
    s3 = get_s3_client()
    with s3.open(strip_s3_protocol(s3_path), "rb") as f:
        parquet_file = pq.ParquetFile(f)
        yield from parquet_file.iter_batches(batch_size=batch_rows)


async def aiter_record_batches(s3_path: str, batch_rows: int = DEFAULT_BATCH_ROWS) -> AsyncIterator[pa.RecordBatch]:
    """Async view of the same stream, for writers that talk to their destination with asyncio.

    The read itself is blocking, so each pull is handed to a thread rather than run on the
    event loop.
    """
    iterator = iter_record_batches(s3_path, batch_rows)
    sentinel = object()

    def next_batch():
        return next(iterator, sentinel)

    while True:
        batch = await sync_to_async(next_batch, thread_sensitive=False)()
        if batch is sentinel:
            return
        yield batch
