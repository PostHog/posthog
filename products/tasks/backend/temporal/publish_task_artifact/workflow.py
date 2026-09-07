"""Replay-safe workflow boundary for one brokered draft publication."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import PublishTaskArtifactInput, finalize_failed_publication, publish_task_artifact


@workflow.defn(name="publish-task-artifact")
class PublishTaskArtifactWorkflow(PostHogWorkflow):
    @workflow.run
    async def run(self, input: PublishTaskArtifactInput) -> None:
        try:
            await workflow.execute_activity(
                publish_task_artifact,
                input,
                start_to_close_timeout=timedelta(minutes=12),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except Exception:
            await workflow.execute_activity(
                finalize_failed_publication,
                input,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise
