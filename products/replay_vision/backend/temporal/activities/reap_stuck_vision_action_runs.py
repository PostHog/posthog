"""Fails VisionActionRun rows stuck in `running` whose workflow is gone, so run history stays truthful."""

from datetime import UTC, datetime
from typing import Any, cast

import structlog
from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.replay_vision.backend.models.vision_action import VisionActionRun, VisionActionRunStatus
from products.replay_vision.backend.temporal.activities.reaping import classify_stale_rows
from products.replay_vision.backend.temporal.constants import (
    REAP_STUCK_VISION_ACTION_RUNS_BATCH_SIZE,
    VISION_ACTION_RUN_STUCK_CUTOFF,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import record_vision_action_runs_reaped

logger = structlog.get_logger(__name__)

# delivery_unknown: the documented stuck-RUNNING cause is the final bookkeeping update failing
# after side effects (Slack/email) may already have gone out — we can't prove non-delivery.
_REAPED_ERROR = {"reaped": "The run stopped without recording an outcome.", "delivery_unknown": True}


def _list_stuck_runs() -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - VISION_ACTION_RUN_STUCK_CUTOFF
    rows = (
        VisionActionRun.all_teams.filter(status=VisionActionRunStatus.RUNNING, created_at__lt=cutoff)
        .order_by("created_at")
        .values("id", "temporal_workflow_id")[:REAP_STUCK_VISION_ACTION_RUNS_BATCH_SIZE]
    )
    # cast: django-stubs types `.values()` rows as a TypedDict, which mypy won't widen to dict[str, Any].
    return cast(list[dict[str, Any]], list(rows))


def _mark_reaped(run_ids: list[Any]) -> int:
    # Status guard keeps this idempotent against workflows that terminated between listing and now.
    # `.update()` bypasses auto_now, so stamp updated_at explicitly.
    return VisionActionRun.all_teams.filter(id__in=run_ids, status=VisionActionRunStatus.RUNNING).update(
        status=VisionActionRunStatus.FAILED,
        error=_REAPED_ERROR,
        updated_at=datetime.now(UTC),
    )


@activity.defn
@track_activity()
async def reap_stuck_vision_action_runs_activity() -> int:
    """Fail running rows past the stuck cutoff whose workflow is no longer open; returns the count reaped."""
    rows = await database_sync_to_async(_list_stuck_runs, thread_sensitive=False)()
    if not rows:
        return 0
    temporal = await async_connect()
    reapable, skipped_open, skipped_temporal_error = await classify_stale_rows(
        temporal, rows, workflow_id_key="temporal_workflow_id"
    )
    reaped = 0
    if reapable:
        reaped = await database_sync_to_async(_mark_reaped, thread_sensitive=False)([row["id"] for row in reapable])
    record_vision_action_runs_reaped(reaped)
    logger.info(
        "replay_vision.reap_stuck_vision_action_runs",
        scanned=len(rows),
        reaped=reaped,
        skipped_open=skipped_open,
        skipped_temporal_error=skipped_temporal_error,
    )
    return reaped
