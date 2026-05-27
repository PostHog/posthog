"""Activities for the daily Replay Vision cleanup sweep."""

import asyncio
import datetime as dt
from collections import Counter as PyCounter
from datetime import timedelta
from typing import Literal
from uuid import UUID

from django.utils import timezone

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.temporal.cleanup_sweep.constants import (
    PRUNE_BATCH_SIZE,
    PRUNE_MAX_BATCHES,
    REAP_DESCRIBE_CONCURRENCY,
    REAP_ERROR_REASON,
    REAP_MAX_CANDIDATES,
)
from products.replay_vision.backend.temporal.cleanup_sweep.types import CleanupSweepInputs, PruneResult, ReapResult
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import FailureKind
from products.replay_vision.backend.temporal.metrics import (
    REPLAY_VISION_CLEANUP_SWEEP_HIT_CAP,
    REPLAY_VISION_CLEANUP_SWEEP_ROWS,
    REPLAY_VISION_FAILURE_KINDS,
    REPLAY_VISION_OBSERVATIONS,
)

logger = structlog.get_logger(__name__)

ClassifyOutcome = Literal["reap", "running", "error"]


def _heartbeat(*payload: object) -> None:
    """Heartbeat that no-ops outside a real activity context (e.g. unit-test invocations)."""
    if activity.in_activity():
        activity.heartbeat(*payload)


_TERMINAL_OBSERVATION_STATUSES = [ObservationStatus.SUCCEEDED, ObservationStatus.FAILED, ObservationStatus.INELIGIBLE]
_IN_FLIGHT_OBSERVATION_STATUSES = [ObservationStatus.PENDING, ObservationStatus.RUNNING]

_TERMINAL_WORKFLOW_STATUSES = frozenset(
    {
        WorkflowExecutionStatus.COMPLETED,
        WorkflowExecutionStatus.FAILED,
        WorkflowExecutionStatus.CANCELED,
        WorkflowExecutionStatus.TERMINATED,
        WorkflowExecutionStatus.TIMED_OUT,
    }
)


@activity.defn
@track_activity()
async def prune_old_observations_activity(inputs: CleanupSweepInputs) -> PruneResult:
    """Delete terminal observation rows older than `retention_days`; batched and capped per-sweep."""
    cutoff = timezone.now() - timedelta(days=inputs.retention_days)
    rows_deleted = 0
    batches = 0
    hit_cap = False
    while True:
        # LIMIT+1 so we can deterministically tell "this was the last batch" from "there may be more"
        # — a strict `len == BATCH_SIZE` check false-positives `hit_cap` at the exact boundary.
        ids = await sync_to_async(_load_prune_batch, thread_sensitive=False)(cutoff)
        if not ids:
            break
        has_more = len(ids) > PRUNE_BATCH_SIZE
        to_delete = ids[:PRUNE_BATCH_SIZE]
        deleted = await sync_to_async(_delete_batch, thread_sensitive=False)(to_delete)
        rows_deleted += deleted
        batches += 1
        _heartbeat({"rows_deleted": rows_deleted, "batches": batches})
        if not has_more:
            break
        if batches >= PRUNE_MAX_BATCHES:
            hit_cap = True
            break

    REPLAY_VISION_CLEANUP_SWEEP_ROWS.labels(action="pruned").inc(rows_deleted)
    if hit_cap:
        REPLAY_VISION_CLEANUP_SWEEP_HIT_CAP.labels(stage="prune").inc()
    logger.info(
        "replay_vision.cleanup_sweep.prune_complete",
        rows_deleted=rows_deleted,
        batches=batches,
        hit_cap=hit_cap,
        cutoff=cutoff.isoformat(),
    )
    return PruneResult(rows_deleted=rows_deleted, batches_run=batches, hit_cap=hit_cap)


@activity.defn
@track_activity()
async def reap_stranded_observations_activity(inputs: CleanupSweepInputs) -> ReapResult:
    """Flip long-running pending/running rows to failed when their workflow is no longer alive in Temporal."""
    cutoff = timezone.now() - timedelta(hours=inputs.stranded_hours)
    candidates = await sync_to_async(_load_stranded_candidates, thread_sensitive=False)(cutoff)
    hit_cap = len(candidates) == REAP_MAX_CANDIDATES
    if not candidates:
        _emit_reap_outcome(
            scanned=0, reaped_by_type=PyCounter(), skipped_running=0, skipped_temporal_error=0, hit_cap=hit_cap
        )
        return ReapResult(hit_cap=hit_cap)

    temporal = await async_connect()
    describe_sem = asyncio.Semaphore(REAP_DESCRIBE_CONCURRENCY)

    async def _classify(observation_id: UUID, workflow_id: str, scanner_type: str) -> tuple[UUID, ClassifyOutcome, str]:
        async with describe_sem:
            outcome = await _classify_workflow(temporal, workflow_id)
            # Heartbeat per describe so a slow Temporal frontend doesn't trip the 2-minute heartbeat timeout
            # before the full asyncio.gather returns.
            _heartbeat({"phase": "classify", "observation_id": str(observation_id)})
            return observation_id, outcome, scanner_type

    classifications = await asyncio.gather(*(_classify(o, w, st) for o, w, st in candidates))

    to_reap_with_type = [(oid, st) for oid, outcome, st in classifications if outcome == "reap"]
    skipped_running = sum(1 for _, outcome, _ in classifications if outcome == "running")
    skipped_temporal_error = sum(1 for _, outcome, _ in classifications if outcome == "error")

    reaped_by_type: PyCounter[str] = PyCounter()
    if to_reap_with_type:
        reaped_count = await sync_to_async(_reap_observations, thread_sensitive=False)(
            [oid for oid, _ in to_reap_with_type]
        )
        # Distribute the (possibly truncated) reaped count across the scanner_type buckets we attempted.
        # Race-skipped rows are absorbed by truncating from the tail; minor over-count is acceptable
        # because the bulk UPDATE is filtered on `status__in=_IN_FLIGHT` and only a race can drop a row.
        running_total = 0
        for _oid, st in to_reap_with_type:
            if running_total >= reaped_count:
                break
            reaped_by_type[st] += 1
            running_total += 1

    _emit_reap_outcome(
        scanned=len(candidates),
        reaped_by_type=reaped_by_type,
        skipped_running=skipped_running,
        skipped_temporal_error=skipped_temporal_error,
        hit_cap=hit_cap,
    )
    return ReapResult(
        scanned=len(candidates),
        reaped=sum(reaped_by_type.values()),
        skipped_running=skipped_running,
        skipped_temporal_error=skipped_temporal_error,
        hit_cap=hit_cap,
    )


def _load_prune_batch(cutoff: dt.datetime) -> list[UUID]:
    # Fetches BATCH_SIZE + 1 so the caller can use the extra row to detect "more remain"
    # without an extra query at the loop's boundary.
    return list(
        ReplayObservation.objects.filter(
            status__in=_TERMINAL_OBSERVATION_STATUSES,
            completed_at__lt=cutoff,
        )
        .order_by("completed_at")
        .values_list("id", flat=True)[: PRUNE_BATCH_SIZE + 1]
    )


def _delete_batch(ids: list[UUID]) -> int:
    deleted, _ = ReplayObservation.objects.filter(id__in=ids).delete()
    return deleted


def _load_stranded_candidates(cutoff: dt.datetime) -> list[tuple[UUID, str, str]]:
    # Ordered oldest-first so backlogs past REAP_MAX_CANDIDATES drain monotonically across sweeps.
    return list(
        ReplayObservation.objects.filter(
            status__in=_IN_FLIGHT_OBSERVATION_STATUSES,
            created_at__lt=cutoff,
        )
        .order_by("created_at")
        .values_list("id", "workflow_id", "scanner_snapshot__scanner_type")[:REAP_MAX_CANDIDATES]
    )


def _reap_observations(ids: list[UUID]) -> int:
    # Filtered on status so a row that legitimately completed between classification and reap is left alone.
    return ReplayObservation.objects.filter(
        id__in=ids,
        status__in=_IN_FLIGHT_OBSERVATION_STATUSES,
    ).update(
        status=ObservationStatus.FAILED,
        error_reason=REAP_ERROR_REASON,
        completed_at=timezone.now(),
    )


async def _classify_workflow(temporal: Client, workflow_id: str) -> ClassifyOutcome:
    """Returns 'reap' (terminal or NOT_FOUND), 'running', or 'error'."""
    if not workflow_id:
        # Empty workflow_id means the row was inserted but the workflow start raced or failed; safe to reap.
        return "reap"
    try:
        desc = await temporal.get_workflow_handle(workflow_id).describe()
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return "reap"
        # Non-NOT_FOUND RPC errors usually indicate a Temporal outage — every candidate this sweep
        # will roll into `skipped_temporal_error`, so the warning lets ops distinguish that from
        # a one-off describe failure.
        logger.warning(
            "replay_vision.cleanup_sweep.describe_rpc_error",
            workflow_id=workflow_id,
            rpc_status=str(e.status),
        )
        return "error"
    except Exception:
        logger.exception("replay_vision.cleanup_sweep.describe_unexpected_error", workflow_id=workflow_id)
        return "error"
    if desc.status in _TERMINAL_WORKFLOW_STATUSES:
        return "reap"
    return "running"


def _emit_reap_outcome(
    *,
    scanned: int,
    reaped_by_type: PyCounter[str],
    skipped_running: int,
    skipped_temporal_error: int,
    hit_cap: bool,
) -> None:
    reaped_total = sum(reaped_by_type.values())
    REPLAY_VISION_CLEANUP_SWEEP_ROWS.labels(action="reaped").inc(reaped_total)
    REPLAY_VISION_CLEANUP_SWEEP_ROWS.labels(action="skipped_running").inc(skipped_running)
    REPLAY_VISION_CLEANUP_SWEEP_ROWS.labels(action="skipped_temporal_error").inc(skipped_temporal_error)
    if hit_cap:
        REPLAY_VISION_CLEANUP_SWEEP_HIT_CAP.labels(stage="reap").inc()
    # Mirror what mark_observation_failed_activity would have done if each reap had gone through it,
    # so failure-rate dashboards include sweep-killed observations.
    for scanner_type, count in reaped_by_type.items():
        REPLAY_VISION_OBSERVATIONS.labels(status="failed", scanner_type=scanner_type).inc(count)
        REPLAY_VISION_FAILURE_KINDS.labels(kind=FailureKind.INTERNAL_ERROR.value, scanner_type=scanner_type).inc(count)
    logger.info(
        "replay_vision.cleanup_sweep.reap_complete",
        scanned=scanned,
        reaped=reaped_total,
        skipped_running=skipped_running,
        skipped_temporal_error=skipped_temporal_error,
        hit_cap=hit_cap,
    )
