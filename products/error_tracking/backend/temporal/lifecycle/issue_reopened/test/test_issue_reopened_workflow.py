import json
import uuid
import asyncio
import dataclasses
from datetime import timedelta

import pytest

from temporalio import activity
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from products.error_tracking.backend.temporal.lifecycle.issue_reopened import workflow as issue_reopened_workflow
from products.error_tracking.backend.temporal.lifecycle.issue_reopened.types import (
    IssueReopenedSnapshot,
    IssueReopenedWorkflowInputs,
    IssueReopenedWorkflowResult,
)
from products.error_tracking.backend.temporal.lifecycle.issue_reopened.workflow import (
    SUMMARY_ON_REOPEN_PATCH,
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
    summarized: list[str] = []
    signal_attempts = 0

    @activity.defn(name="dispatch_issue_reopened_alert_activity")
    async def dispatch_alert(_: IssueReopenedWorkflowInputs) -> None:
        return None

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

    @activity.defn(name="generate_issue_reopened_summary_activity")
    async def generate_summary(inputs: IssueReopenedWorkflowInputs) -> str:
        summarized.append(inputs.issue_id)
        return "generated"

    task_queue = str(uuid.uuid4())
    inputs = _inputs()
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingIssueReopenedWorkflow],
            activities=[dispatch_alert, emit_event, emit_signal, generate_summary],
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
    assert summarized == [inputs.issue_id]
    assert signal_attempts == 2


@pytest.mark.asyncio
async def test_alert_dispatch_runs_even_when_the_internal_event_fails_for_good() -> None:
    dispatched: list[str] = []

    @activity.defn(name="dispatch_issue_reopened_alert_activity")
    async def dispatch_alert(inputs: IssueReopenedWorkflowInputs) -> None:
        dispatched.append(inputs.issue_id)

    @activity.defn(name="emit_issue_reopened_internal_event_activity")
    async def emit_event(_: IssueReopenedWorkflowInputs) -> None:
        raise ApplicationError("kafka unavailable", non_retryable=True)

    @activity.defn(name="emit_issue_reopened_signal_activity")
    async def emit_signal(_: IssueReopenedWorkflowInputs) -> None:
        return None

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingIssueReopenedWorkflow],
            activities=[dispatch_alert, emit_event, emit_signal],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            inputs = _inputs()
            with pytest.raises(WorkflowFailureError):
                await environment.client.execute_workflow(
                    ErrorTrackingIssueReopenedWorkflow.run,
                    inputs,
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

    assert dispatched == [inputs.issue_id]


@pytest.mark.asyncio
async def test_a_failed_summary_neither_holds_the_alert_nor_fails_the_workflow() -> None:
    alerted = asyncio.Event()
    summary_saw_alert = False

    @activity.defn(name="dispatch_issue_reopened_alert_activity")
    async def dispatch_alert(_: IssueReopenedWorkflowInputs) -> None:
        alerted.set()

    @activity.defn(name="emit_issue_reopened_internal_event_activity")
    async def emit_event(_: IssueReopenedWorkflowInputs) -> None:
        return None

    @activity.defn(name="emit_issue_reopened_signal_activity")
    async def emit_signal(_: IssueReopenedWorkflowInputs) -> None:
        return None

    @activity.defn(name="generate_issue_reopened_summary_activity")
    async def generate_summary(_: IssueReopenedWorkflowInputs) -> str:
        nonlocal summary_saw_alert
        await asyncio.wait_for(alerted.wait(), timeout=10)
        summary_saw_alert = True
        raise ApplicationError("summary failed", non_retryable=True)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingIssueReopenedWorkflow],
            activities=[dispatch_alert, emit_event, emit_signal, generate_summary],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await environment.client.execute_workflow(
                ErrorTrackingIssueReopenedWorkflow.run,
                _inputs(),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=1),
            )

    assert result == IssueReopenedWorkflowResult(notified=True)
    assert summary_saw_alert


@pytest.mark.asyncio
async def test_replays_a_history_recorded_before_the_summary_activity(monkeypatch: pytest.MonkeyPatch) -> None:
    @activity.defn(name="dispatch_issue_reopened_alert_activity")
    async def dispatch_alert(_: IssueReopenedWorkflowInputs) -> None:
        return None

    @activity.defn(name="emit_issue_reopened_internal_event_activity")
    async def emit_event(_: IssueReopenedWorkflowInputs) -> None:
        return None

    @activity.defn(name="emit_issue_reopened_signal_activity")
    async def emit_signal(_: IssueReopenedWorkflowInputs) -> None:
        return None

    @activity.defn(name="generate_issue_reopened_summary_activity")
    async def generate_summary(_: IssueReopenedWorkflowInputs) -> str:
        return "generated"

    original_patched = issue_reopened_workflow.workflow.patched

    def before_summary_patch(patch_id: str) -> bool:
        return False if patch_id == SUMMARY_ON_REOPEN_PATCH else original_patched(patch_id)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingIssueReopenedWorkflow],
            activities=[dispatch_alert, emit_event, emit_signal, generate_summary],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with monkeypatch.context() as patched:
                patched.setattr(issue_reopened_workflow.workflow, "patched", before_summary_patch)
                handle = await environment.client.start_workflow(
                    ErrorTrackingIssueReopenedWorkflow.run,
                    _inputs(),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    execution_timeout=timedelta(minutes=1),
                )
                assert await handle.result() == IssueReopenedWorkflowResult(notified=True)
                history = await handle.fetch_history()

    scheduled = [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
    ]
    assert "generate_issue_reopened_summary_activity" not in scheduled
    await Replayer(
        workflows=[ErrorTrackingIssueReopenedWorkflow], workflow_runner=UnsandboxedWorkflowRunner()
    ).replay_workflow(history)
