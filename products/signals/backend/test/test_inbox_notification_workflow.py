import uuid

import pytest
from unittest.mock import patch

from django.test import override_settings

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization, Team

from products.signals.backend.models import SignalReport, SignalReportTask
from products.signals.backend.temporal.inbox_notification import (
    InboxNotificationInput,
    InboxNotificationState,
    SignalReportInboxNotificationWorkflow,
    _compute_inbox_notification_state,
    _send_report_inbox_notifications,
)
from products.tasks.backend.models import Task, TaskRun

TASK_QUEUE = "test-inbox-notification-queue"


def _make_report(team: Team, status: str = SignalReport.Status.READY) -> SignalReport:
    return SignalReport.objects.create(
        team=team, status=status, title="t", summary="s", signal_count=1, total_weight=1.0
    )


def _link_implementation_task(team: Team, report: SignalReport, *, pr_url: str | None, run_status: str) -> None:
    task = Task.objects.create(
        team=team, title="impl", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
    )
    SignalReportTask.objects.create(
        team=team, report=report, task=task, relationship=SignalReportTask.Relationship.IMPLEMENTATION
    )
    TaskRun.objects.create(team=team, task=task, status=run_status, output={"pr_url": pr_url})


@pytest.fixture
def team(db):
    org = Organization.objects.create(name="inbox-notif-org")
    team = Team.objects.create(organization=org, name="inbox-notif-team")
    yield team
    team.delete()
    org.delete()


@pytest.mark.django_db
def test_state_no_implementation_task(team):
    report = _make_report(team)
    state = _compute_inbox_notification_state(team.id, str(report.id))
    assert state == InboxNotificationState(has_implementation_task=False, pr_available=False, task_terminal=False)


@pytest.mark.django_db
def test_state_task_with_pr(team):
    report = _make_report(team)
    _link_implementation_task(team, report, pr_url="https://github.com/o/r/pull/1", run_status=TaskRun.Status.COMPLETED)
    state = _compute_inbox_notification_state(team.id, str(report.id))
    assert state == InboxNotificationState(has_implementation_task=True, pr_available=True, task_terminal=False)


@pytest.mark.django_db
def test_state_task_running_no_pr(team):
    report = _make_report(team)
    _link_implementation_task(team, report, pr_url=None, run_status=TaskRun.Status.IN_PROGRESS)
    state = _compute_inbox_notification_state(team.id, str(report.id))
    assert state == InboxNotificationState(has_implementation_task=True, pr_available=False, task_terminal=False)


@pytest.mark.django_db
def test_state_task_failed_no_pr_is_terminal(team):
    report = _make_report(team)
    _link_implementation_task(team, report, pr_url=None, run_status=TaskRun.Status.FAILED)
    state = _compute_inbox_notification_state(team.id, str(report.id))
    assert state == InboxNotificationState(has_implementation_task=True, pr_available=False, task_terminal=True)


@pytest.mark.django_db
def test_send_skips_when_report_not_ready(team):
    report = _make_report(team, status=SignalReport.Status.SUPPRESSED)
    with patch("products.signals.backend.slack_inbox_notifications.dispatch_inbox_item_notifications") as mock_dispatch:
        sent = _send_report_inbox_notifications(team.id, str(report.id))
    assert sent == 0
    mock_dispatch.assert_not_called()


class _Recorder:
    def __init__(self, states: list[InboxNotificationState]) -> None:
        self._states = states
        self.state_calls = 0
        self.dispatch_calls = 0

    def next_state(self) -> InboxNotificationState:
        state = self._states[min(self.state_calls, len(self._states) - 1)]
        self.state_calls += 1
        return state


async def _run_workflow(recorder: _Recorder) -> int:
    @activity.defn(name="get_inbox_notification_state_activity")
    async def fake_state(_input: InboxNotificationInput) -> InboxNotificationState:
        return recorder.next_state()

    @activity.defn(name="send_report_inbox_notifications_activity")
    async def fake_dispatch(_input: InboxNotificationInput) -> int:
        recorder.dispatch_calls += 1
        return 1

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SignalReportInboxNotificationWorkflow],
            activities=[fake_state, fake_dispatch],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                SignalReportInboxNotificationWorkflow.run,
                InboxNotificationInput(team_id=1, report_id=str(uuid.uuid4())),
                id=f"wf-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )


WAIT = InboxNotificationState(has_implementation_task=True, pr_available=False, task_terminal=False)
NO_TASK = InboxNotificationState(has_implementation_task=False, pr_available=False, task_terminal=False)
PR_READY = InboxNotificationState(has_implementation_task=True, pr_available=True, task_terminal=False)
TERMINAL = InboxNotificationState(has_implementation_task=True, pr_available=False, task_terminal=True)


@pytest.mark.asyncio
@override_settings(SIGNALS_INBOX_PR_NOTIFICATION_TIMEOUT_SECONDS=10, SIGNALS_INBOX_PR_NOTIFICATION_POLL_SECONDS=1)
async def test_workflow_waits_then_notifies_when_pr_opens():
    recorder = _Recorder([WAIT, WAIT, PR_READY])
    sent = await _run_workflow(recorder)
    assert sent == 1
    assert recorder.state_calls == 3
    assert recorder.dispatch_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "states,timeout_seconds,polls",
    [
        ([NO_TASK], 10, False),  # a task-less report can never produce a PR, so skip on the first fetch
        ([WAIT, TERMINAL], 10, True),  # task reaches a terminal state without ever opening a PR
        ([WAIT], 3, True),  # PR never opens, so the wait runs out the timeout
    ],
)
async def test_workflow_skips_when_no_pr_is_produced(states, timeout_seconds, polls):
    recorder = _Recorder(states)
    with override_settings(
        SIGNALS_INBOX_PR_NOTIFICATION_TIMEOUT_SECONDS=timeout_seconds,
        SIGNALS_INBOX_PR_NOTIFICATION_POLL_SECONDS=1,
    ):
        sent = await _run_workflow(recorder)
    assert sent == 0
    assert recorder.dispatch_calls == 0
    if polls:
        assert recorder.state_calls >= 2  # initial fetch + at least one poll before giving up
    else:
        assert recorder.state_calls == 1  # decided on the first fetch — no task means no polling
