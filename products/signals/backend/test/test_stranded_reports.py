import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from temporalio import activity
from temporalio.client import (
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    WorkflowExecutionStatus,
)
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.sync import database_sync_to_async

from products.signals.backend.management.commands.signal_pipeline_status import Command as PipelineStatusCommand
from products.signals.backend.models import SignalReport
from products.signals.backend.signal_metadata import ReportSignalMeta
from products.signals.backend.temporal import metrics
from products.signals.backend.temporal.stranded_reports import (
    SCHEDULE_ID,
    SCHEDULE_INTERVAL,
    STRANDED_FAILURE_REASON,
    WORKFLOW_NAME,
    FailStrandedReportInput,
    FailStrandedReportOutput,
    FindStrandedReportsInput,
    FindStrandedReportsOutput,
    StrandedReport,
    StrandedReportReconcilerInput,
    StrandedReportReconcilerWorkflow,
    fail_stranded_report_activity,
    find_stranded_reports_activity,
)
from products.signals.backend.temporal.stranded_reports_schedule import (
    create_signals_stranded_report_reconciler_schedule,
)
from products.signals.backend.temporal.summary import SignalReportSummaryWorkflow

MODULE = "products.signals.backend.temporal.stranded_reports"
SCHEDULE_MODULE = "products.signals.backend.temporal.stranded_reports_schedule"
SUMMARY_MODULE = "products.signals.backend.temporal.summary"
TASK_QUEUE = "test-stranded-reports-queue"


async def _report(team, *, status=SignalReport.Status.IN_PROGRESS, last_run_minutes_ago=30) -> SignalReport:
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=team, status=status, signal_count=2, total_weight=1.0, run_count=1
    )
    await database_sync_to_async(SignalReport.objects.filter(id=report.id).update)(
        last_run_at=timezone.now() - timedelta(minutes=last_run_minutes_ago)
    )
    await database_sync_to_async(report.refresh_from_db)()
    return report


def _temporal_client(outcomes: dict[str, WorkflowExecutionStatus | Exception]) -> MagicMock:
    client = MagicMock()

    def get_workflow_handle(workflow_id: str) -> MagicMock:
        handle = MagicMock()

        async def describe():
            outcome = outcomes.get(workflow_id, RPCError("not found", RPCStatusCode.NOT_FOUND, b""))
            if isinstance(outcome, Exception):
                raise outcome
            return SimpleNamespace(status=outcome)

        handle.describe = describe
        return handle

    client.get_workflow_handle.side_effect = get_workflow_handle
    return client


def _patched_connect(client: MagicMock):
    return patch(f"{MODULE}.async_connect", new=AsyncMock(return_value=client))


async def _find(client: MagicMock, **kwargs) -> FindStrandedReportsOutput:
    with _patched_connect(client):
        return await ActivityEnvironment().run(find_stranded_reports_activity, FindStrandedReportsInput(**kwargs))


async def _refreshed(report: SignalReport) -> SignalReport:
    return await database_sync_to_async(SignalReport.objects.get)(id=report.id)


def _last_run_at(report: SignalReport) -> datetime:
    assert report.last_run_at is not None
    return report.last_run_at


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "workflow_outcome,expected_status",
    [
        (WorkflowExecutionStatus.TIMED_OUT, "TIMED_OUT"),
        (WorkflowExecutionStatus.TERMINATED, "TERMINATED"),
        (WorkflowExecutionStatus.COMPLETED, "COMPLETED"),
        (RPCError("not found", RPCStatusCode.NOT_FOUND, b""), "NOT_FOUND"),
    ],
)
async def test_find_returns_in_progress_reports_whose_workflow_is_gone(ateam, workflow_outcome, expected_status):
    report = await _report(ateam)
    workflow_id = SignalReportSummaryWorkflow.workflow_id_for(ateam.id, str(report.id))

    output = await _find(_temporal_client({workflow_id: workflow_outcome}))

    assert [s.report_id for s in output.stranded] == [str(report.id)]
    stranded = output.stranded[0]
    assert stranded.workflow_status == expected_status
    assert stranded.team_id == ateam.id
    assert stranded.last_run_at == _last_run_at(report).isoformat()
    assert output.scanned == 1
    assert output.running == 0
    assert output.truncated is False


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "workflow_outcome",
    [
        WorkflowExecutionStatus.RUNNING,
        WorkflowExecutionStatus.CONTINUED_AS_NEW,
        RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b""),
    ],
)
async def test_find_leaves_live_and_unknown_workflows_alone(ateam, workflow_outcome):
    report = await _report(ateam)
    workflow_id = SignalReportSummaryWorkflow.workflow_id_for(ateam.id, str(report.id))

    output = await _find(_temporal_client({workflow_id: workflow_outcome}))

    assert output.stranded == []
    assert output.scanned == 1
    assert output.running == (0 if isinstance(workflow_outcome, RPCError) else 1)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_find_skips_young_reports_and_non_in_progress_statuses(ateam):
    await _report(ateam, last_run_minutes_ago=5)
    await _report(ateam, status=SignalReport.Status.CANDIDATE)
    await _report(ateam, status=SignalReport.Status.READY)

    output = await _find(_temporal_client({}))

    assert output.scanned == 0
    assert output.stranded == []


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_find_takes_the_oldest_first_and_reports_truncation(ateam):
    newest = await _report(ateam, last_run_minutes_ago=40)
    oldest = await _report(ateam, last_run_minutes_ago=120)
    middle = await _report(ateam, last_run_minutes_ago=80)

    output = await _find(_temporal_client({}), limit=2)

    assert [s.report_id for s in output.stranded] == [str(oldest.id), str(middle.id)]
    assert output.truncated is True
    assert str(newest.id) not in [s.report_id for s in output.stranded]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_find_is_a_noop_when_disabled(ateam):
    await _report(ateam)
    client = _temporal_client({})

    with override_settings(SIGNAL_STRANDED_REPORT_RECONCILER_ENABLED=False):
        output = await _find(client)

    assert output == FindStrandedReportsOutput()
    client.get_workflow_handle.assert_not_called()


def _fail_input(report: SignalReport, *, expected_last_run_at: str | None = None) -> FailStrandedReportInput:
    return FailStrandedReportInput(
        team_id=report.team_id,
        report_id=str(report.id),
        expected_last_run_at=expected_last_run_at or _last_run_at(report).isoformat(),
        workflow_status="TIMED_OUT",
        run_count=report.run_count,
        signal_count=report.signal_count,
    )


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_fail_marks_the_report_failed_and_completes_the_pass(ateam):
    report = await _report(ateam)
    meta = {str(report.id): ReportSignalMeta(source_products=["zendesk"], scout_name=None)}

    with (
        patch(f"{MODULE}.fetch_source_products_for_reports", return_value=meta),
        patch(f"{SUMMARY_MODULE}.posthoganalytics.capture") as capture,
    ):
        output = await ActivityEnvironment().run(fail_stranded_report_activity, _fail_input(report))

    assert output == FailStrandedReportOutput(outcome=metrics.STRANDED_OUTCOME_FAILED)
    refreshed = await _refreshed(report)
    assert refreshed.status == SignalReport.Status.FAILED
    assert "TIMED_OUT" in (refreshed.error or "")
    completed = [c for c in capture.call_args_list if c.kwargs["event"] == "signal_report_completed"]
    assert len(completed) == 1
    properties = completed[0].kwargs["properties"]
    assert properties["result"] == "failed"
    assert properties["failure_reason"] == STRANDED_FAILURE_REASON
    assert properties["source_products"] == ["zendesk"]
    assert properties["run_count"] == report.run_count


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_fail_still_fails_the_report_when_source_products_cannot_be_read(ateam):
    report = await _report(ateam)

    with (
        patch(f"{MODULE}.fetch_source_products_for_reports", side_effect=RuntimeError("clickhouse down")),
        patch(f"{SUMMARY_MODULE}.posthoganalytics.capture") as capture,
    ):
        output = await ActivityEnvironment().run(fail_stranded_report_activity, _fail_input(report))

    assert output.outcome == metrics.STRANDED_OUTCOME_FAILED
    assert (await _refreshed(report)).status == SignalReport.Status.FAILED
    assert capture.call_args.kwargs["properties"]["source_products"] == []


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("status", [SignalReport.Status.IN_PROGRESS, SignalReport.Status.READY])
async def test_fail_leaves_a_report_that_moved_since_the_scan_alone(ateam, status):
    report = await _report(ateam, status=status)
    # A newer pass rewrites last_run_at; a later status keeps it. Both must veto the write.
    stale_last_run_at = (_last_run_at(report) - timedelta(minutes=10)).isoformat()
    expected = stale_last_run_at if status == SignalReport.Status.IN_PROGRESS else None

    with (
        patch(f"{MODULE}.fetch_source_products_for_reports", return_value={}),
        patch(f"{SUMMARY_MODULE}.posthoganalytics.capture") as capture,
    ):
        output = await ActivityEnvironment().run(
            fail_stranded_report_activity, _fail_input(report, expected_last_run_at=expected)
        )

    assert output.outcome == metrics.STRANDED_OUTCOME_SKIPPED_CHANGED
    refreshed = await _refreshed(report)
    assert refreshed.status == status
    assert refreshed.error is None
    capture.assert_not_called()


@pytest.mark.asyncio
async def test_workflow_fails_every_stranded_report_even_when_one_raises():
    stranded = [
        StrandedReport(
            team_id=1,
            report_id=str(uuid.uuid4()),
            run_count=1,
            signal_count=1,
            last_run_at=timezone.now().isoformat(),
            workflow_status="TIMED_OUT",
        )
        for _ in range(2)
    ]
    attempted: list[str] = []

    @activity.defn(name="find_stranded_reports_activity")
    async def fake_find(_input: FindStrandedReportsInput) -> FindStrandedReportsOutput:
        return FindStrandedReportsOutput(stranded=stranded, scanned=2)

    @activity.defn(name="fail_stranded_report_activity")
    async def fake_fail(input: FailStrandedReportInput) -> FailStrandedReportOutput:
        attempted.append(input.report_id)
        if input.report_id == stranded[0].report_id:
            raise ApplicationError("boom", non_retryable=True)
        return FailStrandedReportOutput(outcome=metrics.STRANDED_OUTCOME_FAILED)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[StrandedReportReconcilerWorkflow],
            activities=[fake_find, fake_fail],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                StrandedReportReconcilerWorkflow.run,
                StrandedReportReconcilerInput(),
                id=f"stranded-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )

    assert attempted == [s.report_id for s in stranded]


@pytest.fixture
def schedule_helpers():
    with (
        patch(f"{SCHEDULE_MODULE}.a_create_schedule", new_callable=AsyncMock) as create,
        patch(f"{SCHEDULE_MODULE}.a_update_schedule", new_callable=AsyncMock) as update,
        patch(f"{SCHEDULE_MODULE}.a_schedule_exists", new_callable=AsyncMock) as exists,
    ):
        yield {"create": create, "update": update, "exists": exists}


def _assert_reconciler_schedule(schedule) -> None:
    assert isinstance(schedule.action, ScheduleActionStartWorkflow)
    assert schedule.action.workflow == WORKFLOW_NAME
    assert schedule.action.id == SCHEDULE_ID
    assert schedule.action.task_queue == settings.VIDEO_EXPORT_TASK_QUEUE
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert schedule.policy.catchup_window == SCHEDULE_INTERVAL
    assert schedule.spec.intervals == [ScheduleIntervalSpec(every=SCHEDULE_INTERVAL)]


@pytest.mark.asyncio
@pytest.mark.parametrize("exists", [False, True])
async def test_schedule_is_created_when_missing_and_updated_when_present(schedule_helpers, exists):
    schedule_helpers["exists"].return_value = exists
    client = MagicMock()

    await create_signals_stranded_report_reconciler_schedule(client)

    called = schedule_helpers["update"] if exists else schedule_helpers["create"]
    skipped = schedule_helpers["create"] if exists else schedule_helpers["update"]
    called.assert_awaited_once()
    skipped.assert_not_called()
    passed_client, schedule_id, schedule = called.call_args.args
    assert passed_client is client
    assert schedule_id == SCHEDULE_ID
    _assert_reconciler_schedule(schedule)
    if not exists:
        assert called.call_args.kwargs["trigger_immediately"] is False


@pytest.mark.parametrize(
    "stranded_ids,settled",
    [
        (["report-a"], True),
        ([], False),
    ],
)
def test_pipeline_status_does_not_wait_on_stranded_reports(stranded_ids, settled):
    status = {
        "postgres": {"in_progress": 1, "total": 1},
        "temporal": {"stranded_report_ids": stranded_ids},
    }

    result = PipelineStatusCommand()._is_settled(
        status, expected_signals=1, ch_count=1, prev_ch_count=1, stable_polls=1
    )

    assert result is settled
