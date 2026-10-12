import asyncio
from datetime import UTC, datetime
from itertools import islice

import structlog
from google.genai import Client as RawGenAIClient
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect
from posthog.temporal.common.heartbeat import Heartbeater

from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.gemini import gemini_api_key
from products.replay_vision.backend.temporal.gemini_cleanup_sweep.constants import (
    DELETE_CONCURRENCY,
    DESCRIBE_CONCURRENCY,
    MAX_FILES_PER_SWEEP,
    MAX_STORAGE_LIST_FILES,
    STORAGE_LIST_PAGE_SIZE,
    SWEEP_MIN_AGE,
)
from products.replay_vision.backend.temporal.gemini_cleanup_sweep.tracking import (
    delete_and_untrack,
    index_size,
    iter_tracked_files,
)
from products.replay_vision.backend.temporal.gemini_cleanup_sweep.types import (
    CleanupSweepInputs,
    CleanupSweepResult,
    GeminiStorageUsage,
    TrackedFile,
)
from products.replay_vision.backend.temporal.metrics import push_gemini_cleanup_gauges, record_gemini_cleanup_files

logger = structlog.get_logger(__name__)

_FILE_RESULTS = (
    "deleted",
    "delete_failed",
    "skipped_running",
    "skipped_too_young",
    "skipped_temporal_error",
    "skipped_invalid_value",
)

_TERMINAL_STATUSES = frozenset(
    {
        WorkflowExecutionStatus.COMPLETED,
        WorkflowExecutionStatus.FAILED,
        WorkflowExecutionStatus.CANCELED,
        WorkflowExecutionStatus.TERMINATED,
        WorkflowExecutionStatus.TIMED_OUT,
    }
)


async def _classify_workflow(temporal: Client, workflow_id: str) -> str:
    """Returns ``"delete"``, ``"running"``, or ``"error"``."""
    try:
        desc = await temporal.get_workflow_handle(workflow_id).describe()
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return "delete"
        return "error"
    except Exception:
        return "error"

    if desc.status in _TERMINAL_STATUSES:
        return "delete"
    return "running"


@activity.defn(name="replay_vision_sweep_gemini_files_activity")
@track_activity()
async def sweep_gemini_files_activity(inputs: CleanupSweepInputs) -> CleanupSweepResult:
    """Reclaims orphaned Gemini files. Failures counted, never raised."""
    # Continuous background heartbeats — a degraded-API delete fan-out otherwise outlives the heartbeat timeout.
    async with Heartbeater(factor=4):
        return await _sweep_gemini_files(inputs)


async def _sweep_gemini_files(inputs: CleanupSweepInputs) -> CleanupSweepResult:
    raw_client = RawGenAIClient(api_key=gemini_api_key())
    temporal = await async_connect()
    cutoff = datetime.now(UTC) - SWEEP_MIN_AGE

    total_tracked = await index_size()
    hit_max_files_cap = total_tracked > MAX_FILES_PER_SWEEP

    scanned = 0
    skipped_too_young = 0
    skipped_invalid_value = 0
    candidates: list[TrackedFile] = []
    async for tracked in iter_tracked_files(limit=MAX_FILES_PER_SWEEP):
        scanned += 1
        if tracked is None:
            skipped_invalid_value += 1
            continue
        if tracked.uploaded_at > cutoff:
            skipped_too_young += 1
            continue
        candidates.append(tracked)
    activity.heartbeat({"phase": "scanned", "scanned": scanned, "candidates": len(candidates)})

    describe_sem = asyncio.Semaphore(DESCRIBE_CONCURRENCY)

    async def _classify(tracked: TrackedFile) -> tuple[TrackedFile, str]:
        async with describe_sem:
            outcome = await _classify_workflow(temporal, tracked.workflow_id)
            return tracked, outcome

    classifications = await asyncio.gather(*(_classify(t) for t in candidates))
    activity.heartbeat({"phase": "classified", "classified": len(classifications)})

    to_delete = [t for t, outcome in classifications if outcome == "delete"]
    skipped_running = sum(1 for _, outcome in classifications if outcome == "running")
    skipped_temporal_error = sum(1 for _, outcome in classifications if outcome == "error")

    base_result = CleanupSweepResult(
        scanned=scanned,
        skipped_too_young=skipped_too_young,
        skipped_invalid_value=skipped_invalid_value,
        skipped_running=skipped_running,
        skipped_temporal_error=skipped_temporal_error,
        hit_max_files_cap=hit_max_files_cap,
    )

    delete_sem = asyncio.Semaphore(DELETE_CONCURRENCY)

    async def _delete(tracked: TrackedFile) -> bool:
        async with delete_sem:
            # On transient failure the key is kept for next-cycle retry; the 48h TTL backstops.
            return await delete_and_untrack(
                raw_client,
                tracked.gemini_file_name,
                log_source="replay_vision.cleanup_sweep",
                workflow_id=tracked.workflow_id,
                signals_type="cleanup-sweep",
            )

    delete_results = await asyncio.gather(*(_delete(t) for t in to_delete))
    deleted = sum(1 for r in delete_results if r)
    delete_failed = sum(1 for r in delete_results if not r)

    storage = await _measure_storage(raw_client)
    result = base_result.model_copy(update={"deleted": deleted, "delete_failed": delete_failed, "storage": storage})
    for name in _FILE_RESULTS:
        record_gemini_cleanup_files(name, getattr(result, name))
    await asyncio.to_thread(push_gemini_cleanup_gauges, total_tracked, storage)
    logger.info(
        "replay_vision.cleanup_sweep.cycle_complete",
        scanned=result.scanned,
        deleted=result.deleted,
        skipped_running=result.skipped_running,
        skipped_too_young=result.skipped_too_young,
        skipped_invalid_value=result.skipped_invalid_value,
        skipped_temporal_error=result.skipped_temporal_error,
        delete_failed=result.delete_failed,
        hit_max_files_cap=result.hit_max_files_cap,
        storage=storage.model_dump() if storage else None,
        signals_type="cleanup-sweep",
    )
    return result


def _list_storage(raw_client: RawGenAIClient) -> GeminiStorageUsage:
    now = datetime.now(UTC)
    files = 0
    total_bytes = 0
    oldest_created_at = now
    for file in islice(raw_client.files.list(config={"page_size": STORAGE_LIST_PAGE_SIZE}), MAX_STORAGE_LIST_FILES):
        files += 1
        total_bytes += file.size_bytes or 0
        if file.create_time and file.create_time < oldest_created_at:
            oldest_created_at = file.create_time
    return GeminiStorageUsage(
        files=files,
        total_bytes=total_bytes,
        oldest_age_seconds=(now - oldest_created_at).total_seconds(),
        truncated=files == MAX_STORAGE_LIST_FILES,
    )


async def _measure_storage(raw_client: RawGenAIClient) -> GeminiStorageUsage | None:
    """Lists every file in the Gemini project, which is what counts against its storage quota.

    The Redis index only knows files whose tracking write succeeded, so this listing also sees the files
    the sweep can never reach. A failed listing returns None and never fails the sweep.
    """
    try:
        storage = await asyncio.to_thread(_list_storage, raw_client)
    except Exception:
        logger.exception("replay_vision.cleanup_sweep.storage_list_failed", signals_type="cleanup-sweep")
        return None
    activity.heartbeat({"phase": "storage_listed", "files": storage.files})
    if storage.truncated:
        logger.warning(
            "replay_vision.cleanup_sweep.storage_list_truncated",
            max_files=MAX_STORAGE_LIST_FILES,
            signals_type="cleanup-sweep",
        )
    return storage
