from __future__ import annotations

from asgiref.sync import sync_to_async

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor import (
    process_batch as process_sync,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    PendingBatch,
)


async def process_batch(batch: PendingBatch) -> None:
    # thread_sensitive=False: the default would funnel every batch through
    # asgiref's process-global single-thread executor, reducing the consumer's
    # real parallelism to 1 regardless of max_concurrency. Each batch is
    # self-contained (own Django reads after close_old_connections, own duckgres
    # connection), so cross-thread execution is safe.
    await sync_to_async(process_sync, thread_sensitive=False)(batch)
