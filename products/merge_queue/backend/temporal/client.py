"""Fire-and-forget trial-workflow start (mirrors `products/tasks/backend/temporal/client.py`)."""

import asyncio

from django.conf import settings

from temporalio.common import WorkflowIDReusePolicy

from posthog.temporal.common.client import sync_connect

from products.merge_queue.backend.temporal.trial_workflow import TrialWorkflow, TrialWorkflowInputs


def trial_workflow_id(trial_id: str) -> str:
    return f"merge-queue-trial-{trial_id}"


def start_trial_workflow(trial_id: str) -> None:
    """Start the trial workflow without waiting for it (called from the sync engine)."""
    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            TrialWorkflow.get_name(),
            TrialWorkflowInputs(trial_id=trial_id),
            id=trial_workflow_id(trial_id),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            task_queue=settings.MERGE_QUEUE_TASK_QUEUE,
        )
    )
