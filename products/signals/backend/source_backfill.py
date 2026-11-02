import logging

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.client import sync_connect

logger = logging.getLogger(__name__)


def trigger_error_tracking_backfill(team_id: int) -> None:
    from products.signals.backend.temporal.backfill_error_tracking import (  # noqa: PLC0415 - keeps Temporal activities off API route loading
        BackfillErrorTrackingInput,
        BackfillErrorTrackingWorkflow,
    )

    try:
        client = sync_connect()

        async def start_backfill() -> None:
            await client.start_workflow(
                "backfill-error-tracking",
                BackfillErrorTrackingInput(team_id=team_id),
                id=BackfillErrorTrackingWorkflow.workflow_id_for(team_id),
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

        async_to_sync(start_backfill)()
    except Exception:
        logger.exception("Failed to start error tracking backfill", extra={"team_id": team_id})
