import logging

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import sync_connect

logger = logging.getLogger(__name__)


def _start_error_tracking_backfill(team_id: int, reuse_policy: WorkflowIDReusePolicy) -> None:
    from products.signals.backend.temporal.backfill_error_tracking import (  # noqa: PLC0415 - keeps Temporal activities off API route loading
        BackfillErrorTrackingInput,
        BackfillErrorTrackingWorkflow,
    )

    client = sync_connect()

    async def start_backfill() -> None:
        await client.start_workflow(
            "backfill-error-tracking",
            BackfillErrorTrackingInput(team_id=team_id),
            id=BackfillErrorTrackingWorkflow.workflow_id_for(team_id),
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=reuse_policy,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    async_to_sync(start_backfill)()


def trigger_error_tracking_backfill(team_id: int) -> None:
    try:
        _start_error_tracking_backfill(team_id, WorkflowIDReusePolicy.ALLOW_DUPLICATE)
    except Exception:
        logger.exception("Failed to start error tracking backfill", extra={"team_id": team_id})


def start_onboarding_error_tracking_backfill(team_id: int) -> None:
    try:
        _start_error_tracking_backfill(team_id, WorkflowIDReusePolicy.REJECT_DUPLICATE)
    except WorkflowAlreadyStartedError:
        # Temporal can accept the start before the worker persists the onboarding job status.
        pass
