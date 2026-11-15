"""
Adapter that connects the BatchConsumer to the existing Delta Lake loading logic.

Converts a PendingBatch into an ExportSignalMessage dict and delegates to
process_message(). This exists because ProcessBatchFn expects an async callable
that takes a PendingBatch, but the existing processor works with ExportSignalMessage
dicts. Once process_message is refactored to accept PendingBatch directly, this
adapter and to_export_signal() can be removed.

The BatchConsumer handles retries and status updates around this function — it
only needs to raise on failure.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from asgiref.sync import sync_to_async

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor import (
    process_message,
    process_messages,
)
from products.warehouse_sources_queue.backend.core.jobs_db import PendingBatch


async def process_batch(
    batch: PendingBatch,
    verify_ownership: Callable[[], None] | None = None,
    *,
    executor: ThreadPoolExecutor | None = None,
) -> None:
    """Load a single batch into Delta Lake, reusing the existing processor.

    `executor` is the pool that holds the thread for the full load. The consumer passes a dedicated
    pool, because the load waits for nested jobs on the loop's default executor. A load that runs
    on the default executor can hold the thread that its own nested job needs. See `thread_pools`.
    """
    # thread_sensitive=False: the default single-thread executor would cap the pod's
    # real parallelism at 1; process_message is self-contained, so cross-thread is safe.
    # `latest_attempt` counts attempts already recorded, so the delivery starting now is the next
    # one — same arithmetic the consumer uses when it stamps the status row.
    await sync_to_async(process_message, thread_sensitive=False, executor=executor)(
        batch.to_export_signal(), verify_ownership=verify_ownership, attempt=batch.latest_attempt + 1
    )


async def process_batches(
    batches: list[PendingBatch],
    verify_ownership: Callable[[], None] | None = None,
    *,
    executor: ThreadPoolExecutor | None = None,
) -> None:
    """Load consecutive batches of one run into Delta Lake as a single write."""
    await sync_to_async(process_messages, thread_sensitive=False, executor=executor)(
        [batch.to_export_signal() for batch in batches],
        verify_ownership=verify_ownership,
        attempt=max(batch.latest_attempt for batch in batches) + 1,
    )
