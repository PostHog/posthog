import uuid
import random
import asyncio
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from django.db import OperationalError

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async

from products.signals.backend.daily_limit import DailyReportLimitGate
from products.signals.backend.models import SignalReport
from products.signals.backend.quota import SelfDrivingQuotaGate
from products.signals.backend.report_generation.research import ActionabilityChoice
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.startup_failure import RESEARCH_STARTUP_FAILURE, ResearchStartupFailure
from products.signals.backend.temporal.agentic.report import (
    RESEARCH_SANDBOX_UNAVAILABLE_ERROR_TYPE,
    RunAgenticReportInput,
    RunAgenticReportOutput,
)
from products.signals.backend.temporal.agentic.select_repository import SelectRepositoryInput
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeInput, SafetyJudgeOutput
from products.signals.backend.temporal.signal_queries import FetchSignalsForReportInput, FetchSignalsForReportOutput
from products.signals.backend.temporal.summary import (
    EMPTY_FETCH_RETRY_ATTEMPTS,
    CheckReportQuotaGateInput,
    MarkReportFailedInput,
    MarkReportInProgressInput,
    MarkReportPendingInput,
    MarkReportReadyInput,
    NotifyResearchStartupFailureInput,
    PublishReportCompletedInput,
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
        research_choice: ActionabilityChoice = ActionabilityChoice.NOT_ACTIONABLE,
        research_metrics: list[dict[str, object]] | None = None,
        checks_snapshot: dict[str, str] | None = None,
        selected_repository: str | None = "owner/repo",
        spend_failures: int = 0,
        spend_owner_available: bool = True,
        research_errors: list[Exception] | None = None,
        github_optional: bool = False,
    ) -> None:
        self.gate_answers = gate_answers or {}
        self.fetch_results = fetch_results or [[_signal_data()]]
        self.has_assigned_signals = has_assigned_signals
        self.research_choice = research_choice
        self.research_metrics = research_metrics
        self.checks_snapshot = checks_snapshot
        self.checks_summary: str | None = None
        self.checks_error: str | None = None
        self.checks_monitoring_enabled = False
        self.selected_repository = selected_repository
        self.research_errors = list(research_errors or [])
        self.failure_error_types: list[str | None] = []
        self.failure_startups: list[ResearchStartupFailure | None] = []
        self.startup_notice_attempts = 0
        self.github_optional = github_optional
        self.gate_checks: list[str] = []
        self.fetches = 0
        self.claimed_before_fetch: list[bool] = []
        self.assigned_signal_checks = 0
        self.failure_reasons: list[str | None] = []
        self.marks_in_progress = 0
        self.safety_checks = 0
        self.repo_selections = 0
        self.researches = 0
        self.spend_publications = 0
        self.spend_failures = spend_failures
        self.spend_owner_available = spend_owner_available
        self.reverts = 0
        self.resets = 0
        self.failures = 0
        self.pending_inputs: list[MarkReportPendingInput] = []
        self.ready_inputs: list[MarkReportReadyInput] = []


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


def test_legacy_agentic_activity_payload_defaults_metrics_to_preserve() -> None:
    legacy_payload = {
        "title": "Legacy title",
        "summary": "Legacy summary",
        "choice": ActionabilityChoice.NOT_ACTIONABLE.value,
        "priority": None,
        "explanation": "Legacy history",
        "already_addressed": False,
        "repository": "owner/repo",
    }
    payloads = pydantic_data_converter.payload_converter.to_payloads([legacy_payload])

    (decoded,) = pydantic_data_converter.payload_converter.from_payloads(payloads, [RunAgenticReportOutput])

    assert decoded.metrics is None
    assert decoded.charts is None
    assert decoded.checks_snapshot is None
    assert decoded.checks_monitoring_enabled is False


async def _run_summary_workflow(recorder: _Recorder) -> None:
    @activity.defn(name="github_optional_pilot_activity")
    async def fake_pilot(team_id: int) -> bool:
        return recorder.github_optional

    @activity.defn(name="check_report_quota_gate_activity")
    async def fake_quota(input: CheckReportQuotaGateInput) -> bool:
        recorder.gate_checks.append(input.stage)
        return recorder.gate_answers.get(input.stage, False)

    @activity.defn(name="fetch_signals_for_report_activity")
    async def fake_fetch(input: FetchSignalsForReportInput) -> FetchSignalsForReportOutput:
        signals = recorder.fetch_results[min(recorder.fetches, len(recorder.fetch_results) - 1)]
        recorder.fetches += 1
        recorder.claimed_before_fetch.append(recorder.marks_in_progress > 0)
        return FetchSignalsForReportOutput(signals=signals)

    @activity.defn(name="report_has_assigned_signals_activity")
    async def fake_has_assigned_signals(input: ReportHasAssignedSignalsInput) -> bool:
        recorder.assigned_signal_checks += 1
        return recorder.has_assigned_signals

    @activity.defn(name="report_spend_owner_activity")
    async def fake_spend_owner(input: SignalReportSummaryWorkflowInputs) -> str | None:
        if not recorder.spend_owner_available:
            return None
        return input.report_id

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
        return RepoSelectionResult(repository=recorder.selected_repository, reason="no repository matched")

    @activity.defn(name="run_agentic_report_activity")
    async def fake_research(input: RunAgenticReportInput) -> RunAgenticReportOutput:
        recorder.researches += 1
        if recorder.research_errors:
            raise recorder.research_errors.pop(0)
        return RunAgenticReportOutput(
            title="t",
            summary="s",
            choice=recorder.research_choice,
            priority=None,
            explanation="e",
            already_addressed=False,
            repository=recorder.selected_repository,
            metrics=recorder.research_metrics,
            checks_snapshot=recorder.checks_snapshot,
            checks_monitoring_enabled=recorder.checks_monitoring_enabled,
            checks_summary=recorder.checks_summary,
            checks_error=recorder.checks_error,
        )

    @activity.defn(name="mark_report_pending_input_activity")
    async def fake_mark_pending(input: MarkReportPendingInput) -> None:
        recorder.pending_inputs.append(input)

    @activity.defn(name="mark_report_ready_activity")
    async def fake_mark_ready(input: MarkReportReadyInput) -> bool:
        recorder.ready_inputs.append(input)
        return False

    @activity.defn(name="publish_report_completed_activity")
    async def fake_publish(input: PublishReportCompletedInput) -> None:
        return None

    @activity.defn(name="check_report_task_settlement_activity")
    async def fake_task_settlement(input: SignalReportSummaryWorkflowInputs) -> None:
        return None

    @activity.defn(name="publish_report_spend_activity")
    async def fake_publish_spend(input: SignalReportSummaryWorkflowInputs) -> None:
        recorder.spend_publications += 1
        if recorder.spend_publications <= recorder.spend_failures:
            raise OperationalError("Transient accounting failure")

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
        recorder.failure_error_types.append(input.error_type)
        recorder.failure_startups.append(input.startup_failure)

    @activity.defn(name="notify_research_startup_failure_activity")
    async def fake_startup_notification(input: NotifyResearchStartupFailureInput) -> None:
        assert recorder.failures == 1
        assert input.failure == recorder.failure_startups[0]
        recorder.startup_notice_attempts += 1
        if recorder.startup_notice_attempts == 1:
            raise OperationalError("Notification temporarily unavailable")

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
                fake_pilot,
                fake_fetch,
                fake_has_assigned_signals,
                fake_mark_in_progress,
                fake_spend_owner,
                fake_safety,
                fake_select_repo,
                fake_research,
                fake_mark_pending,
                fake_mark_ready,
                fake_publish,
                fake_publish_spend,
                fake_task_settlement,
                fake_revert,
                fake_reset,
                fake_failed,
                fake_startup_notification,
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
@pytest.mark.parametrize("spend_failures", [0, 3])
async def test_open_gates_let_the_run_flow_through(spend_failures: int) -> None:
    recorder = _Recorder(gate_answers={}, spend_failures=spend_failures)
    await _run_summary_workflow(recorder)
    assert recorder.gate_checks == ["summary_entry", "pre_repo_selection", "pre_research"]
    assert recorder.researches == 1
    assert recorder.spend_publications == spend_failures + 1
    assert recorder.reverts == 0
    assert recorder.failures == 0


def _sandbox_unavailable() -> ApplicationError:
    return ApplicationError("sandbox gone", type=RESEARCH_SANDBOX_UNAVAILABLE_ERROR_TYPE)


@pytest.mark.asyncio
async def test_research_retries_after_a_sandbox_outage_instead_of_failing_the_report():
    recorder = _Recorder(research_errors=[_sandbox_unavailable() for _ in range(2)])
    await _run_summary_workflow(recorder)
    assert recorder.researches == 3
    assert recorder.failures == 0
    assert recorder.marks_in_progress == 1
    assert recorder.spend_publications == 1


@pytest.mark.asyncio
async def test_research_fails_the_report_once_the_sandbox_retry_budget_is_spent():
    recorder = _Recorder(research_errors=[_sandbox_unavailable() for _ in range(8)])
    with pytest.raises(WorkflowFailureError):
        await _run_summary_workflow(recorder)
    assert recorder.researches == 8
    assert recorder.failures == 1
    assert recorder.failure_reasons == ["research_sandbox_unavailable"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "research_error,error_type",
    [
        (ApplicationError("No JSON in initial turn", type="output_parse_failed"), "output_parse_failed"),
        (RuntimeError("sandbox failed"), "RuntimeError"),
    ],
)
async def test_research_does_not_retry_other_activity_errors(research_error: Exception, error_type: str):
    recorder = _Recorder(research_errors=[research_error, research_error])
    with pytest.raises(WorkflowFailureError):
        await _run_summary_workflow(recorder)
    assert recorder.researches == 2
    assert recorder.failures == 1
    assert recorder.failure_reasons == ["agentic_activity_error"]
    assert recorder.failure_error_types == [error_type]


@pytest.mark.asyncio
@pytest.mark.parametrize("requires_action,attempts", [(True, 1), (False, 2)])
async def test_research_startup_retry_policy_and_failure_details_survive_temporal(requires_action: bool, attempts: int):
    payload = {
        "failure": {
            "provider": "claude",
            "phase": "sdk_initialization",
            "reason": "proxy_invalid" if requires_action else None,
            "retryability": "requires_action" if requires_action else "unknown",
        },
        "task_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "repository": "example/research",
    }
    error = ApplicationError(
        "Research could not start", payload, type=RESEARCH_STARTUP_FAILURE, non_retryable=requires_action
    )
    recorder = _Recorder(research_errors=[error, error])
    with pytest.raises(WorkflowFailureError):
        await _run_summary_workflow(recorder)
    assert recorder.researches == attempts
    assert recorder.failures == 1
    assert recorder.failure_startups[0] is not None
    assert str(recorder.failure_startups[0].run_id) == payload["run_id"]
    assert recorder.failure_startups[0].failure.retryability == ("requires_action" if requires_action else "unknown")
    assert recorder.startup_notice_attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "choice,target",
    [
        (ActionabilityChoice.REQUIRES_HUMAN_INPUT, "pending"),
        (ActionabilityChoice.IMMEDIATELY_ACTIONABLE, "ready"),
    ],
)
@pytest.mark.parametrize("checks_error", [None, "checks.0.probe_hints: too_long"])
async def test_metric_payload_reaches_the_report_transition(choice, target, checks_error):
    metrics = [{"metric_id": "affected-users", "kind": "affected_users", "value": 12}]
    snapshot = {"check-1": "2026-10-02T12:00:00+00:00"}
    recorder = _Recorder(research_choice=choice, research_metrics=metrics, checks_snapshot=snapshot)
    recorder.checks_summary = "Expected impact matches the reconciled checks."
    recorder.checks_error = checks_error
    recorder.checks_monitoring_enabled = True

    await _run_summary_workflow(recorder)

    inputs = recorder.pending_inputs if target == "pending" else recorder.ready_inputs
    assert len(inputs) == 1
    assert inputs[0].metrics == metrics
    assert inputs[0].checks_snapshot == snapshot
    assert inputs[0].checks_monitoring_enabled is True
    assert inputs[0].checks_summary == recorder.checks_summary
    assert inputs[0].checks_error == checks_error


@pytest.mark.asyncio
@pytest.mark.parametrize("github_optional", [False, True])
async def test_no_repository_researches_only_for_the_pilot(github_optional):
    recorder = _Recorder(
        selected_repository=None,
        github_optional=github_optional,
        research_choice=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
    )

    await _run_summary_workflow(recorder)

    if github_optional:
        assert recorder.researches == 1
        assert recorder.pending_inputs == []
        assert recorder.ready_inputs[0].title == "t"
        assert recorder.failures == 0
        return
    assert recorder.researches == 0
    assert len(recorder.pending_inputs) == 1
    pending = recorder.pending_inputs[0]
    assert pending.keep_existing_content is True
    assert pending.title == "Repository selection required"
    assert pending.summary == "Could not automatically select a repository: no repository matched"
    assert pending.suggested_prompts is None
    assert pending.pending_reason == "repo_selection_required"
    assert pending.note == "Could not automatically select a repository: no repository matched"


# ---------------------------------------------------------------------------
# Empty fetch: ClickHouse lag must not fail a report that has signals assigned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_without_an_open_spend_owner_makes_no_paid_calls():
    recorder = _Recorder(spend_owner_available=False)
    await _run_summary_workflow(recorder)
    assert recorder.fetches == 0
    assert recorder.safety_checks == 0
    assert recorder.researches == 0
    assert recorder.spend_publications == 0


@pytest.mark.asyncio
async def test_empty_first_fetch_is_retried_and_run_proceeds():
    recorder = _Recorder(fetch_results=[[], [], [_signal_data()]])
    await _run_summary_workflow(recorder)
    assert recorder.fetches == 3
    assert all(recorder.claimed_before_fetch)
    assert recorder.researches == 1
    assert recorder.spend_publications == 1
    assert recorder.failures == 0
    assert recorder.assigned_signal_checks == 0


@pytest.mark.asyncio
async def test_persistently_empty_fetch_leaves_report_for_repromotion_when_signals_are_assigned():
    recorder = _Recorder(fetch_results=[[]], has_assigned_signals=True)
    await _run_summary_workflow(recorder)
    assert recorder.fetches == 1 + EMPTY_FETCH_RETRY_ATTEMPTS
    assert recorder.assigned_signal_checks == 1
    assert recorder.marks_in_progress == 1
    assert recorder.reverts == 1
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
