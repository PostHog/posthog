"""Marks provably-orphaned pending/running observations as failed so they stop blocking re-scans and eating quota."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.temporal.constants import (
    OBSERVATION_ORPHAN_CUTOFF,
    REAP_ORPHANED_OBSERVATIONS_BATCH_SIZE,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import FailureKind
from products.replay_vision.backend.temporal.metrics import REPLAY_VISION_FAILURE_KINDS, REPLAY_VISION_OBSERVATIONS

logger = structlog.get_logger(__name__)

_LIVE_STATUSES = (ObservationStatus.PENDING, ObservationStatus.RUNNING)
_ORPHANED_ERROR_REASON = f"{FailureKind.ORPHANED.value}:The analysis stopped without recording an outcome."


def _list_stale_observations() -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - OBSERVATION_ORPHAN_CUTOFF
    return list(
        ReplayObservation.objects.filter(status__in=_LIVE_STATUSES, created_at__lt=cutoff)
        .order_by("created_at")
        .values("id", "workflow_id", "scanner_snapshot")[:REAP_ORPHANED_OBSERVATIONS_BATCH_SIZE]
    )


async def _workflow_is_open(temporal: Client, workflow_id: str) -> bool | None:
    """Whether the latest run of `workflow_id` is still open; `None` when Temporal couldn't answer."""
    try:
        desc = await temporal.get_workflow_handle(workflow_id).describe()
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return False
        return None
    except Exception:
        return None
    return desc.status == WorkflowExecutionStatus.RUNNING


def _mark_orphaned(observation_id: UUID, scanner_type: str) -> bool:
    updated = ReplayObservation.objects.filter(pk=observation_id, status__in=_LIVE_STATUSES).update(
        status=ObservationStatus.FAILED,
        error_reason=_ORPHANED_ERROR_REASON,
        completed_at=datetime.now(UTC),
    )
    if not updated:
        return False  # Raced a terminal transition — leave the row alone.
    REPLAY_VISION_OBSERVATIONS.labels(status="failed", scanner_type=scanner_type).inc()
    REPLAY_VISION_FAILURE_KINDS.labels(kind=FailureKind.ORPHANED.value, scanner_type=scanner_type).inc()
    logger.info(
        "replay_vision.observation.reaped",
        observation_id=str(observation_id),
        scanner_type=scanner_type,
    )
    return True


@activity.defn
@track_activity()
async def reap_orphaned_observations_activity() -> int:
    """Fail pending/running rows past the orphan cutoff whose workflow is no longer open; returns the count reaped.

    The age filter alone proves the *original* workflow is closed (its execution timeout has long expired),
    but a re-trigger reuses the same deterministic workflow id and can reclaim an old PENDING row — the
    describe check keeps the reaper's hands off rows a live run currently owns.
    """
    rows = await database_sync_to_async(_list_stale_observations, thread_sensitive=False)()
    if not rows:
        return 0
    temporal = await async_connect()
    reaped = 0
    skipped_open = 0
    skipped_temporal_error = 0
    for row in rows:
        if row["workflow_id"]:
            is_open = await _workflow_is_open(temporal, row["workflow_id"])
            if is_open:
                skipped_open += 1
                continue
            if is_open is None:
                skipped_temporal_error += 1  # Can't prove it's closed — skip; the next tick retries.
                continue
        snapshot = row["scanner_snapshot"] or {}
        scanner_type = snapshot.get("scanner_type") or "unknown"
        if await database_sync_to_async(_mark_orphaned, thread_sensitive=False)(row["id"], scanner_type):
            reaped += 1
    logger.info(
        "replay_vision.reap_orphaned_observations",
        scanned=len(rows),
        reaped=reaped,
        skipped_open=skipped_open,
        skipped_temporal_error=skipped_temporal_error,
    )
    return reaped
