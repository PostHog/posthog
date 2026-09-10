"""Identifier-only Temporal handoff for prepared Pulse artifacts."""

from __future__ import annotations

from datetime import timedelta

import temporalio.common
import temporalio.activity
import temporalio.workflow

from posthog.temporal.common.base import PostHogWorkflow

from products.subscriptions.backend.facade.temporal import (
    PREPARE_PROACTIVE_ARTIFACT_WORKFLOW_NAME,
    ProactiveArtifactPreparationInput,
)


@temporalio.activity.defn
def prepare_proactive_artifact(input: ProactiveArtifactPreparationInput) -> None:
    """Run the durable facade once. Its exact replays protect external writes."""
    from products.subscriptions.backend.facade.artifacts import (  # noqa: PLC0415 - Temporal sandbox must not import Django models
        prepare_proactive_artifact_for_run,
    )

    prepare_proactive_artifact_for_run(team_id=input.team_id, run_id=input.run_id)


@temporalio.workflow.defn(name=PREPARE_PROACTIVE_ARTIFACT_WORKFLOW_NAME)
class PrepareProactiveArtifactWorkflow(PostHogWorkflow):
    @temporalio.workflow.run
    async def run(self, input: ProactiveArtifactPreparationInput) -> None:
        await temporalio.workflow.execute_activity(
            prepare_proactive_artifact,
            input,
            start_to_close_timeout=timedelta(minutes=12),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )


WORKFLOWS = [PrepareProactiveArtifactWorkflow]
ACTIVITIES = [prepare_proactive_artifact]
