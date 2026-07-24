import json
import uuid
import dataclasses

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.error_tracking.backend.temporal.lifecycle.issue_reopened.types import (
    IssueReopenedSnapshot,
    IssueReopenedWorkflowInputs,
    IssueReopenedWorkflowResult,
)
from products.error_tracking.backend.temporal.lifecycle.issue_reopened.workflow import (
    ErrorTrackingIssueReopenedWorkflow,
)


def _inputs() -> IssueReopenedWorkflowInputs:
    return IssueReopenedWorkflowInputs(
        notification_id=str(uuid.uuid4()),
        team_id=1,
        issue_id=str(uuid.uuid4()),
        issue=IssueReopenedSnapshot(
            name="TypeError",
            description="Something failed",
            status="active",
            created_at="2026-07-21T12:00:00Z",
        ),
        fingerprint="fingerprint",
        event_uuid=str(uuid.uuid4()),
        event_timestamp="2026-07-21T12:00:00Z",
    )


def test_parse_inputs_accepts_cymbal_issue_reopened_notification() -> None:
    inputs = _inputs()
    payload = {
        **dataclasses.asdict(inputs),
        "type": "issue_reopened",
        "event_properties": {"$exception_list": [{"type": "TypeError", "value": "boom"}]},
    }

    assert ErrorTrackingIssueReopenedWorkflow.parse_inputs([json.dumps(payload)]) == inputs


@pytest.mark.asyncio
async def test_retries_and_emits_both_reopened_side_effects() -> None:
    emitted_events: list[str] = []
    emitted_signals: list[str] = []
    signal_attempts = 0

    @activity.defn(name="emit_issue_reopened_internal_event_activity")
    async def emit_event(inputs: IssueReopenedWorkflowInputs) -> None:
        emitted_events.append(inputs.issue_id)

    @activity.defn(name="emit_issue_reopened_signal_activity")
    async def emit_signal(inputs: IssueReopenedWorkflowInputs) -> None:
        nonlocal signal_attempts
        signal_attempts += 1
        if signal_attempts == 1:
            raise RuntimeError("transient signal failure")
        emitted_signals.append(inputs.issue_id)

    task_queue = str(uuid.uuid4())
    inputs = _inputs()
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingIssueReopenedWorkflow],
            activities=[emit_event, emit_signal],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await environment.client.execute_workflow(
                ErrorTrackingIssueReopenedWorkflow.run,
                inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result == IssueReopenedWorkflowResult(notified=True)
    assert emitted_events == [inputs.issue_id]
    assert emitted_signals == [inputs.issue_id]
    assert signal_attempts == 2
