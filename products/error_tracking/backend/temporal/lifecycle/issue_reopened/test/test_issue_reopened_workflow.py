import json
import uuid
import asyncio
import dataclasses
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized
from temporalio import activity
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from posthog.models.activity_logging.activity_log import ActivityLog

from products.error_tracking.backend.models import ErrorTrackingIssue
from products.error_tracking.backend.temporal.lifecycle.issue_reopened import workflow as issue_reopened_workflow
from products.error_tracking.backend.temporal.lifecycle.issue_reopened.activities import (
    record_issue_reopened_activity_log_activity,
)
from products.error_tracking.backend.temporal.lifecycle.issue_reopened.types import (
    IssueReopenedSnapshot,
    IssueReopenedWorkflowInputs,
    IssueReopenedWorkflowResult,
    ReopenedByRelease,
)
from products.error_tracking.backend.temporal.lifecycle.issue_reopened.workflow import (
    ACTIVITY_LOG_ON_REOPEN_PATCH,
    SUMMARY_ON_REOPEN_PATCH,
    ErrorTrackingIssueReopenedWorkflow,
)

RELEASE = ReopenedByRelease(
    id="01982721-5e00-7000-8000-000000000010",
    version="2.4.0",
    project="checkout-web",
    created_at="2026-07-21T11:00:00Z",
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


@pytest.mark.parametrize(
    "reopened_by_release, previous_status",
    [(None, None), (RELEASE, "resolved")],
    ids=["older_cymbal_new_occurrence", "new_release"],
)
def test_parse_inputs_accepts_cymbal_issue_reopened_notification(
    reopened_by_release: ReopenedByRelease | None, previous_status: str | None
) -> None:
    inputs = dataclasses.replace(_inputs(), reopened_by_release=reopened_by_release, previous_status=previous_status)
    payload = {
        **dataclasses.asdict(inputs),
        "type": "issue_reopened",
        "event_properties": {"$exception_list": [{"type": "TypeError", "value": "boom"}]},
    }
    for key in ("reopened_by_release", "previous_status"):
        if payload[key] is None:
            del payload[key]

    assert ErrorTrackingIssueReopenedWorkflow.parse_inputs([json.dumps(payload)]) == inputs


class TestRecordIssueReopenedActivityLogActivity(BaseTest):
    @parameterized.expand(
        [
            ("new_occurrence_of_archived_issue", None, "archived", "archived", {"reason": "new_occurrence"}),
            (
                "new_release",
                RELEASE,
                "resolved",
                "resolved",
                {"reason": "new_release", "release": dataclasses.asdict(RELEASE)},
            ),
            ("older_cymbal_without_previous_status", None, None, "resolved", {"reason": "new_occurrence"}),
        ]
    )
    def test_records_the_reopen_once_and_skips_a_missing_issue(
        self,
        _name: str,
        reopened_by_release: ReopenedByRelease | None,
        previous_status: str | None,
        expected_before: str,
        expected_payload: dict,
    ) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="TypeError")
        inputs = dataclasses.replace(
            _inputs(),
            team_id=self.team.id,
            issue_id=str(issue.id),
            reopened_by_release=reopened_by_release,
            previous_status=previous_status,
        )

        record_issue_reopened_activity_log_activity(inputs)
        record_issue_reopened_activity_log_activity(inputs)
        record_issue_reopened_activity_log_activity(
            dataclasses.replace(inputs, notification_id=str(uuid.uuid4()), issue_id=str(uuid.uuid4()))
        )

        activity_log = ActivityLog.objects.get(team_id=self.team.id, scope="ErrorTrackingIssue")
        assert (activity_log.item_id, activity_log.activity, activity_log.user) == (str(issue.id), "updated", None)
        assert activity_log.detail is not None
        assert activity_log.detail["name"] == "TypeError"
        assert activity_log.detail["changes"] == [
            {
                "type": "ErrorTrackingIssue",
                "action": "changed",
                "field": "status",
                "before": expected_before,
                "after": "active",
            }
        ]
        assert activity_log.detail["trigger"] == {
            "job_type": "error_tracking_ingestion",
            "job_id": inputs.notification_id,
            "payload": {
                **expected_payload,
                "event_uuid": inputs.event_uuid,
                "exception_timestamp": "2026-07-21T12:00:00Z",
            },
        }


@pytest.mark.asyncio
async def test_retries_and_emits_both_reopened_side_effects() -> None:
    emitted_events: list[str] = []
    emitted_signals: list[str] = []
    summarized: list[str] = []
    recorded: list[str] = []
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

    @activity.defn(name="record_issue_reopened_activity_log_activity")
    async def record_activity_log(inputs: IssueReopenedWorkflowInputs) -> None:
        recorded.append(inputs.issue_id)

    task_queue = str(uuid.uuid4())
    inputs = _inputs()
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingIssueReopenedWorkflow],
            activities=[dispatch_alert, emit_event, emit_signal, generate_summary, record_activity_log],
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
    assert recorded == [inputs.issue_id]
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
@pytest.mark.parametrize(
    "failing_activity",
    ["generate_issue_reopened_summary_activity", "record_issue_reopened_activity_log_activity"],
    ids=["summary", "activity_log"],
)
async def test_a_failed_fail_open_activity_neither_holds_the_alert_nor_fails_the_workflow(
    failing_activity: str,
) -> None:
    alerted = asyncio.Event()
    failure_saw_alert = False

    async def fail_after_the_alert(name: str) -> None:
        nonlocal failure_saw_alert
        if name != failing_activity:
            return
        await asyncio.wait_for(alerted.wait(), timeout=10)
        failure_saw_alert = True
        raise ApplicationError(f"{name} failed", non_retryable=True)

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
    async def generate_summary(_: IssueReopenedWorkflowInputs) -> None:
        await fail_after_the_alert("generate_issue_reopened_summary_activity")

    @activity.defn(name="record_issue_reopened_activity_log_activity")
    async def record_activity_log(_: IssueReopenedWorkflowInputs) -> None:
        await fail_after_the_alert("record_issue_reopened_activity_log_activity")

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingIssueReopenedWorkflow],
            activities=[dispatch_alert, emit_event, emit_signal, generate_summary, record_activity_log],
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
    assert failure_saw_alert


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch_id, activity_name",
    [
        (SUMMARY_ON_REOPEN_PATCH, "generate_issue_reopened_summary_activity"),
        (ACTIVITY_LOG_ON_REOPEN_PATCH, "record_issue_reopened_activity_log_activity"),
    ],
    ids=["summary", "activity_log"],
)
async def test_replays_a_history_recorded_before_a_patched_activity(
    monkeypatch: pytest.MonkeyPatch, patch_id: str, activity_name: str
) -> None:
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

    @activity.defn(name="record_issue_reopened_activity_log_activity")
    async def record_activity_log(_: IssueReopenedWorkflowInputs) -> None:
        return None

    original_patched = issue_reopened_workflow.workflow.patched

    def before_the_patch(requested: str) -> bool:
        return False if requested == patch_id else original_patched(requested)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingIssueReopenedWorkflow],
            activities=[dispatch_alert, emit_event, emit_signal, generate_summary, record_activity_log],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with monkeypatch.context() as patched:
                patched.setattr(issue_reopened_workflow.workflow, "patched", before_the_patch)
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
    assert activity_name not in scheduled
    await Replayer(
        workflows=[ErrorTrackingIssueReopenedWorkflow], workflow_runner=UnsandboxedWorkflowRunner()
    ).replay_workflow(history)
