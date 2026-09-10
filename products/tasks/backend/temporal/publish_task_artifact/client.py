"""Client helpers for starting the brokered publication workflow."""

from __future__ import annotations

import asyncio
from uuid import UUID

from django.conf import settings

from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.client import sync_connect

from products.tasks.backend.temporal.publish_task_artifact.activities import PublishTaskArtifactInput


def publication_workflow_input(*, staged_run_id: UUID, publication_id: UUID) -> PublishTaskArtifactInput:
    """Keep the outbound workflow payload bounded to authoritative identifiers."""
    return PublishTaskArtifactInput(staged_run_id=staged_run_id, publication_id=publication_id)


def dispatch_publication_workflow(*, staged_run_id: UUID, publication_id: UUID) -> None:
    """Start one replay-safe, identifier-only publication workflow after execution stops."""
    asyncio.run(
        sync_connect().start_workflow(
            "publish-task-artifact",
            publication_workflow_input(staged_run_id=staged_run_id, publication_id=publication_id),
            id=f"task-draft-publication-{publication_id}",
            task_queue=settings.TASKS_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
    )
