import uuid
import random
import asyncio
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async

from products.signals.backend.daily_limit import DailyReportLimitGate
from products.signals.backend.models import SignalReport
from products.signals.backend.quota import SelfDrivingQuotaGate
from products.signals.backend.report_generation.research import ActionabilityChoice
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.temporal.agentic.report import RunAgenticReportInput, RunAgenticReportOutput
from products.signals.backend.temporal.agentic.select_repository import SelectRepositoryInput
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeInput, SafetyJudgeOutput
from products.signals.backend.temporal.signal_queries import FetchSignalsForReportInput, FetchSignalsForReportOutput
from products.signals.backend.temporal.summary import (
    EMPTY_FETCH_RETRY_ATTEMPTS,
    CheckReportQuotaGateInput,
    MarkReportFailedInput,
    MarkReportInProgressInput,
    ReportHasAssignedSignalsInput,
    ResetReportToPotentialInput,
    RevertReportToCandidateInput,
    SignalReportSummaryWorkflow,
    check_report_quota_gate_activity,
    report_has_assigned_signals_activity,
    revert_report_to_candidate_activity,
)
from products.signals.backend.temporal.types import SignalData, SignalReportSummaryWorkflowInputs

SUMMARY_MODULE_PATH = "products.signals.backend.temporal.summary"
TASK_QUEUE = "test-summary-workflow-queue"


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"SummaryWorkflowOrg-{random.randint(1, 99999)}",
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SummaryWorkflowTeam-{random.randint(1, 99999)}",
    )
    yield team
    await sync_to_async(team.delete)()


# ---------------------------------------------------------------------------
# check_report_quota_gate_activity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("enforced", [True, False])
async def test_check_activity_returns_enforced(ateam, enforced):
    with (
        patch(
            f"{SUMMARY_MODULE_PATH}.self_driving_quota_gate",
            return_value=SelfDrivingQuotaGate(limited=True, enforced=enforced),
        ),
        patch("products.signals.backend.quota.posthoganalytics.capture"),
    ):
        result = await check_report_quota_gate_activity(
            CheckReportQuotaGateInput(team_id=ateam.id, report_id=str(uuid.uuid4()), stage="summary_entry")
        )
    assert result is enforced


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_check_activity_pauses_on_daily_limit_with_billing_clear(ateam):
    # The daily report limit must pause the run on its own: it has no enforcement flag, so
    # `limited` alone blocks even while the billing quota gate stays clear.
    with (
        patch(
            f"{SUMMARY_MODULE_PATH}.daily_report_limit_gate",
            return_value=DailyReportLimitGate(limited=True, limit=3, reports_today=3),
        ),
        patch("products.signals.backend.daily_limit.posthoganalytics.capture") as capture,
    ):
        result = await check_report_quota_gate_activity(
            CheckReportQuotaGateInput(team_id=ateam.id, report_id=str(uuid.uuid4()), stage="pre_research")
        )
    assert result is True
    assert capture.call_args.kwargs["event"] == "signal_report_daily_limit_paused"
    properties = capture.call_args.kwargs["properties"]
    assert properties["stage"] == "pre_research"
    assert properties["limit"] == 3
    assert properties["reports_today"] == 3


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_check_activity_fails_open_when_team_lookup_errors():
    # The never-raises contract: a failure inside the gate check must resolve to "proceed", not
    # bubble into the workflow's except handler and mark the report failed.
    result = await check_report_quota_gate_activity(
        CheckReportQuotaGateInput(team_id=99_999_999, report_id=str(uuid.uuid4()), stage="summary_entry")
    )
    assert result is False


# ---------------------------------------------------------------------------
# revert_report_to_candidate_activity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_revert_returns_in_progress_report_to_candidate(ateam):
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        total_weight=2.0,
        signal_count=2,
        signals_at_run=5,
        run_count=2,
    )

    await revert_report_to_candidate_activity(RevertReportToCandidateInput(team_id=ateam.id, report_id=str(report.id)))

    refreshed = await database_sync_to_async(SignalReport.objects.get)(id=report.id)
    assert refreshed.status == SignalReport.Status.CANDIDATE
    # run_count feeds Temporal workflow IDs and must never roll back on a quota pause.
    assert refreshed.run_count == 2


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("status", [SignalReport.Status.CANDIDATE, SignalReport.Status.READY])
async def test_revert_noops_when_report_is_not_in_progress(ateam, status):
    # An activity retry landing after another run already moved the report on must not clobber it.
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=status,
        title="t",
        summary="s",
        total_weight=2.0,
        signal_count=2,
    )

    await revert_report_to_candidate_activity(RevertReportToCandidateInput(team_id=ateam.id, report_id=str(report.id)))

    refreshed = await database_sync_to_async(SignalReport.objects.get)(id=report.id)
    assert refreshed.status == status


# ---------------------------------------------------------------------------
# Workflow wiring: the gates must short-circuit the run at the right points
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(
        self,
        gate_answers: dict[str, bool] | None = None,
        # Signals returned by successive fetches; the last entry repeats once exhausted.
        fetch_results: list[list[SignalData]] | None = None,
        has_assigned_signals: bool = True,
    ) -> None:
        self.gate_answers = gate_answers or {}
        self.fetch_results = fetch_results or [[_signal_data()]]
        self.has_assigned_signals = has_assigned_signals
        self.gate_checks: list[str] = []
        self.fetches = 0
        self.assigned_signal_checks = 0
        self.failure_reasons: list[str | None] = []
        self.marks_in_progress = 0
        self.safety_checks = 0
        self.repo_selections = 0
        self.researches = 0
        self.reverts = 0
        self.resets = 0
        self.failures = 0


def _signal_data() -> SignalData:
    return SignalData(
        signal_id=str(uuid.uuid4()),
        content="something happened",
        source_product="error_tracking",
        source_type="issue",
        source_id=str(uuid.uuid4()),
        weight=1.0,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def _run_summary_workflow(recorder: _Recorder) -> None:
    @activity.defn(name="check_report_quota_gate_activity")
    async def fake_quota(input: CheckReportQuotaGateInput) -> bool:
        recorder.gate_checks.append(input.stage)
        return recorder.gate_answers.get(input.stage, False)

    @activity.defn(name="fetch_signals_for_report_activity")
    async def fake_fetch(input: FetchSignalsForReportInput) -> FetchSignalsForReportOutput:
        signals = recorder.fetch_results[min(recorder.fetches, len(recorder.fetch_results) - 1)]
        recorder.fetches += 1
        return FetchSignalsForReportOutput(signals=signals)

    @activity.defn(name="report_has_assigned_signals_activity")
    async def fake_has_assigned_signals(input: ReportHasAssignedSignalsInput) -> bool:
        recorder.assigned_signal_checks += 1
        return recorder.has_assigned_signals

    @activity.defn(name="mark_report_in_progress_activity")
    async def fake_mark_in_progress(input: MarkReportInProgressInput) -> None:
        recorder.marks_in_progress += 1

    @activity.defn(name="report_safety_judge_activity")
    async def fake_safety(input: SafetyJudgeInput) -> SafetyJudgeOutput:
        recorder.safety_checks += 1
        return SafetyJudgeOutput(safe=True, explanation="ok")

    @activity.defn(name="select_repository_activity")
    async def fake_select_repo(input: SelectRepositoryInput) -> RepoSelectionResult:
        recorder.repo_selections += 1
        return RepoSelectionResult(repository="owner/repo", reason="selected")

    @activity.defn(name="run_agentic_report_activity")
    async def fake_research(input: RunAgenticReportInput) -> RunAgenticReportOutput:
        recorder.researches += 1
        # NOT_ACTIONABLE terminates the workflow via the reset path, keeping the fake surface small.
        return RunAgenticReportOutput(
            title="t",
            summary="s",
            choice=ActionabilityChoice.NOT_ACTIONABLE,
            priority=None,
            explanation="e",
            already_addressed=False,
            repository="owner/repo",
        )

    @activity.defn(name="revert_report_to_candidate_activity")
    async def fake_revert(input: RevertReportToCandidateInput) -> None:
        recorder.reverts += 1

    @activity.defn(name="reset_report_to_potential_activity")
    async def fake_reset(input: ResetReportToPotentialInput) -> None:
        recorder.resets += 1

    @activity.defn(name="mark_report_failed_activity")
    async def fake_failed(input: MarkReportFailedInput) -> None:
        recorder.failures += 1
        recorder.failure_reasons.append(input.failure_reason)

    # The production self-driving worker runs with the pydantic data converter; the default converter
    # mangles the enum/pydantic payloads these activities exchange (RepoSelectionResult,
    # ActionabilityChoice), sending the workflow down the wrong decision branch.
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SignalReportSummaryWorkflow],
            activities=[
                fake_quota,
                fake_fetch,
                fake_has_assigned_signals,
                fake_mark_in_progress,
                fake_safety,
                fake_select_repo,
                fake_research,
                fake_revert,
                fake_reset,
                fake_failed,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await asyncio.wait_for(
                env.client.execute_workflow(
                    SignalReportSummaryWorkflow.run,
                    SignalReportSummaryWorkflowInputs(team_id=1, report_id=str(uuid.uuid4())),
                    id=f"summary-workflow-{uuid.uuid4()}",
                    task_queue=TASK_QUEUE,
                ),
                timeout=30,
            )


@pytest.mark.asyncio
async def test_entry_gate_stops_run_before_any_work():
    recorder = _Recorder(gate_answers={"summary_entry": True})
    await _run_summary_workflow(recorder)
    assert recorder.gate_checks == ["summary_entry"]
    # Nothing downstream runs, and the report row is untouched (no in_progress transition to revert).
    assert recorder.fetches == 0
    assert recorder.marks_in_progress == 0
    assert recorder.reverts == 0
    assert recorder.failures == 0


@pytest.mark.asyncio
async def test_pre_research_gate_reverts_report_and_skips_research():
    recorder = _Recorder(gate_answers={"pre_research": True})
    await _run_summary_workflow(recorder)
    assert recorder.gate_checks == ["summary_entry", "pre_repo_selection", "pre_research"]
    assert recorder.marks_in_progress == 1
    assert recorder.repo_selections == 1
    # The expensive research never starts, and the in_progress report is handed back to candidate.
    assert recorder.researches == 0
    assert recorder.reverts == 1
    assert recorder.failures == 0


@pytest.mark.asyncio
async def test_open_gates_let_the_run_flow_through():
    recorder = _Recorder(gate_answers={})
    await _run_summary_workflow(recorder)
    assert recorder.gate_checks == ["summary_entry", "pre_repo_selection", "pre_research"]
    assert recorder.researches == 1
    assert recorder.reverts == 0
    assert recorder.failures == 0


# ---------------------------------------------------------------------------
# Empty fetch: ClickHouse lag must not fail a report that has signals assigned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_first_fetch_is_retried_and_run_proceeds():
    recorder = _Recorder(fetch_results=[[], [], [_signal_data()]])
    await _run_summary_workflow(recorder)
    assert recorder.fetches == 3
    assert recorder.researches == 1
    assert recorder.failures == 0
    assert recorder.assigned_signal_checks == 0


@pytest.mark.asyncio
async def test_persistently_empty_fetch_leaves_report_for_repromotion_when_signals_are_assigned():
    recorder = _Recorder(fetch_results=[[]], has_assigned_signals=True)
    await _run_summary_workflow(recorder)
    assert recorder.fetches == 1 + EMPTY_FETCH_RETRY_ATTEMPTS
    assert recorder.assigned_signal_checks == 1
    # Neither researched nor failed: the report stays where it is and grouping re-promotes it.
    assert recorder.marks_in_progress == 0
    assert recorder.researches == 0
    assert recorder.failures == 0


@pytest.mark.asyncio
async def test_persistently_empty_fetch_fails_report_with_no_assigned_signals():
    recorder = _Recorder(fetch_results=[[]], has_assigned_signals=False)
    await _run_summary_workflow(recorder)
    assert recorder.fetches == 1 + EMPTY_FETCH_RETRY_ATTEMPTS
    assert recorder.researches == 0
    assert recorder.failure_reasons == ["no_signals_found"]


# ---------------------------------------------------------------------------
# report_has_assigned_signals_activity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("signal_count,expected", [(0, False), (1, True)])
async def test_report_has_assigned_signals_reads_postgres_signal_count(ateam, signal_count, expected):
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.CANDIDATE,
        total_weight=1.0,
        signal_count=signal_count,
    )
    result = await report_has_assigned_signals_activity(
        ReportHasAssignedSignalsInput(team_id=ateam.id, report_id=str(report.id))
    )
    assert result is expected
