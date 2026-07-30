"""Fails VisionActionRun rows stuck in `running` whose workflow is gone, so run history stays truthful."""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import structlog
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.replay_vision.backend.models.vision_action import VisionActionRun, VisionActionRunStatus
from products.replay_vision.backend.temporal.constants import (
    REAP_STUCK_VISION_ACTION_RUNS_BATCH_SIZE,
    VISION_ACTION_RUN_STUCK_CUTOFF,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import record_vision_action_runs_reaped

logger = structlog.get_logger(__name__)


def _list_stuck_runs() -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - VISION_ACTION_RUN_STUCK_CUTOFF
    rows = (
        VisionActionRun.all_teams.filter(status=VisionActionRunStatus.RUNNING, created_at__lt=cutoff)
        .order_by("created_at")
        .values("id", "temporal_workflow_id")[:REAP_STUCK_VISION_ACTION_RUNS_BATCH_SIZE]
    )
    # cast: django-stubs types `.values()` rows as a TypedDict, which mypy won't widen to dict[str, Any].
    return cast(list[dict[str, Any]], list(rows))


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


def _mark_reaped(run_id: UUID) -> bool:
    # Status guard keeps this idempotent against a workflow that terminated between listing and now.
    updated = VisionActionRun.all_teams.filter(id=run_id, status=VisionActionRunStatus.RUNNING).update(
        status=VisionActionRunStatus.FAILED,
        error={"reaped": "The run stopped without recording an outcome."},
    )
    return updated > 0


@activity.defn
@track_activity()
async def reap_stuck_vision_action_runs_activity() -> int:
    """Fail running rows past the stuck cutoff whose workflow is no longer open; returns the count reaped."""
    rows = await database_sync_to_async(_list_stuck_runs, thread_sensitive=False)()
    if not rows:
        return 0
    temporal = await async_connect()
    reaped = 0
    skipped_open = 0
    skipped_temporal_error = 0
    for row in rows:
        if row["temporal_workflow_id"]:
            is_open = await _workflow_is_open(temporal, row["temporal_workflow_id"])
            if is_open:
                skipped_open += 1
                continue
            if is_open is None:
                skipped_temporal_error += 1  # Can't prove it's closed — leave it for the next tick.
                continue
        if await database_sync_to_async(_mark_reaped, thread_sensitive=False)(row["id"]):
            reaped += 1
    record_vision_action_runs_reaped(reaped)
    logger.info(
        "replay_vision.reap_stuck_vision_action_runs",
        scanned=len(rows),
        reaped=reaped,
        skipped_open=skipped_open,
        skipped_temporal_error=skipped_temporal_error,
    )
    return reaped
