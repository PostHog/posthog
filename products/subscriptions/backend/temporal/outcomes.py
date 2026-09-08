"""One deterministic Temporal readout for an adopted proactive artifact."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

import temporalio.common
import temporalio.activity
import temporalio.workflow

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

PROACTIVE_OUTCOME_READOUT_WORKFLOW_NAME = "proactive-outcome-readout"


@frozen
class ProactiveOutcomeReadoutInput:
    team_id: int
    outcome_id: UUID
    due_at: datetime


@temporalio.activity.defn
def read_proactive_outcome(input: ProactiveOutcomeReadoutInput) -> str:
    """Perform the durable outcome readout once the workflow reaches its due time."""
    from products.subscriptions.backend.facade.outcomes import (  # noqa: PLC0415 - Temporal sandbox must not import Django models
        read_outcome_once,
    )

    return read_outcome_once(team_id=input.team_id, outcome_id=input.outcome_id).status


@temporalio.workflow.defn(name=PROACTIVE_OUTCOME_READOUT_WORKFLOW_NAME)
class ReadProactiveOutcomeWorkflow(PostHogWorkflow):
    @temporalio.workflow.run
    async def run(self, input: ProactiveOutcomeReadoutInput) -> str:
        remaining = input.due_at - temporalio.workflow.now()
        if remaining > timedelta():
            await temporalio.workflow.sleep(remaining)
        return await temporalio.workflow.execute_activity(
            read_proactive_outcome,
            input,
            start_to_close_timeout=timedelta(minutes=12),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )


WORKFLOWS = [ReadProactiveOutcomeWorkflow]
ACTIVITIES = [read_proactive_outcome]
