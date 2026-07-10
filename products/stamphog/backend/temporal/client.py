"""Temporal client helper for starting the stamphog PR review workflow.

Modeled on ``products/tasks/backend/temporal/client.py``: a thin fire-and-forget
bridge from Django (Celery task / transaction.on_commit) into Temporal. The
workflow itself owns the ReviewRun lifecycle once started.
"""

import logging

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

logger = logging.getLogger(__name__)

STAMPHOG_REVIEW_WORKFLOW = "stamphog-review"


def _stamphog_task_queue() -> str:
    # Falls back to the general-purpose queue until a dedicated stamphog queue exists.
    return getattr(settings, "STAMPHOG_TASK_QUEUE", settings.GENERAL_PURPOSE_TASK_QUEUE)


@async_to_sync
async def execute_stamphog_review_workflow(review_run_id: str, team_id: int) -> None:
    """Start the ``stamphog-review`` workflow for a queued ReviewRun.

    Decorated with ``async_to_sync`` so it bridges cleanly out of the synchronous
    ``transaction.on_commit`` callback the Celery task registers, without nesting a
    second event loop. Fire-and-forget: a duplicate delivery re-enters
    ``ALLOW_DUPLICATE_FAILED_ONLY`` and is a no-op while a workflow is live.
    """
    # Deferred so the workflow module (and the temporalio workflow sandbox it drags
    # in) stays off the Celery/web import path that this client rides on.
    from products.stamphog.backend.temporal.workflow import (  # noqa: PLC0415 — keep the workflow sandbox off the import path
        StamphogReviewInput,
    )

    client = await async_connect()
    workflow_id = f"stamphog-review-{review_run_id}"
    await client.start_workflow(
        STAMPHOG_REVIEW_WORKFLOW,
        StamphogReviewInput(review_run_id=review_run_id, team_id=team_id),
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=_stamphog_task_queue(),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )
    logger.info(
        "stamphog_review_workflow_started",
        extra={"review_run_id": review_run_id, "team_id": team_id, "workflow_id": workflow_id},
    )
