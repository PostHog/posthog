import asyncio
from datetime import UTC, datetime

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
    TrackedFile,
)

logger = structlog.get_logger(__name__)

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

    result = base_result.model_copy(update={"deleted": deleted, "delete_failed": delete_failed})
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
        signals_type="cleanup-sweep",
    )
    return result
