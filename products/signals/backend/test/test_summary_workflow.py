import uuid
import random
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, patch

from django.conf import settings

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio import activity, workflow
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

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
from products.signals.backend.temporal.signal_implementation import (
    SignalImplementationFinalizerWorkflow,
    SignalImplementationInput,
)
from products.signals.backend.temporal.signal_queries import FetchSignalsForReportInput, FetchSignalsForReportOutput
from products.signals.backend.temporal.summary import (
    EMPTY_FETCH_RETRY_ATTEMPTS,
    CheckReportQuotaGateInput,
    ImplementationBufferInput,
    ImplementationRunRef,
    MarkReportFailedInput,
    MarkReportInProgressInput,
    MarkReportReadyInput,
    MaybeAutostartImplementationInput,
    PublishReportCompletedInput,
    ReportHasAssignedSignalsInput,
    ResetReportToPotentialInput,
    RevertReportToCandidateInput,
    SignalReportSummaryWorkflow,
    check_report_quota_gate_activity,
    maybe_autostart_implementation_activity,
    report_has_assigned_signals_activity,
    revert_report_to_candidate_activity,
    select_research_signal_key,
)
from products.signals.backend.temporal.types import SignalData, SignalReportSummaryWorkflowInputs

SUMMARY_MODULE_PATH = "products.signals.backend.temporal.summary"
TASK_QUEUE = settings.VIDEO_EXPORT_TASK_QUEUE


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
        self.safety_signal_keys: list[str | None] = []
        self.research_signal_keys: list[str | None] = []
        self.finalizer_inputs: list[SignalImplementationInput] = []
        self.expected_finalizer_inputs: list[SignalImplementationInput] = []
        self.actionability_choice = ActionabilityChoice.NOT_ACTIONABLE
        self.implementation_run: ImplementationRunRef | None = None
        self.research_started = asyncio.Event()
        self.continue_research = asyncio.Event()
        self.continue_research.set()


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


@workflow.defn(name="signal-implementation-finalizer")
class StubSignalImplementationFinalizerWorkflow:
    @workflow.run
    async def run(self, input: SignalImplementationInput) -> None:
        await workflow.execute_activity(
            "record_signal_finalizer_input_activity",
            input,
            start_to_close_timeout=timedelta(seconds=10),
        )


async def _run_summary_workflow(
    recorder: _Recorder,
    inputs: SignalReportSummaryWorkflowInputs | None = None,
    *,
    legacy_stage_handoffs: bool = False,
    signal_during_first_pass: list[str] | None = None,
) -> WorkflowHistory:
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
        recorder.safety_signal_keys.append(input.signal_key)
        return SafetyJudgeOutput(safe=True, explanation="ok")

    @activity.defn(name="select_repository_activity")
    async def fake_select_repo(input: SelectRepositoryInput) -> RepoSelectionResult:
        recorder.repo_selections += 1
        return RepoSelectionResult(repository="owner/repo", reason="selected")

    @activity.defn(name="run_agentic_report_activity")
    async def fake_research(input: RunAgenticReportInput) -> RunAgenticReportOutput:
        recorder.researches += 1
        recorder.research_signal_keys.append(input.signal_key)
        recorder.research_started.set()
        await recorder.continue_research.wait()
        return RunAgenticReportOutput(
            title="t",
            summary="s",
            choice=recorder.actionability_choice,
            priority=None,
            explanation="e",
            already_addressed=False,
            repository="owner/repo",
        )

    @activity.defn(name="mark_report_ready_activity")
    async def fake_mark_ready(input: MarkReportReadyInput) -> bool:
        return False

    @activity.defn(name="publish_report_completed_activity")
    async def fake_publish(input: PublishReportCompletedInput) -> None:
        pass

    @activity.defn(name="implementation_buffer_seconds_activity")
    async def fake_implementation_buffer(input: ImplementationBufferInput) -> int:
        return 0

    @activity.defn(name="maybe_autostart_implementation_activity")
    async def fake_autostart(input: MaybeAutostartImplementationInput) -> ImplementationRunRef | None:
        return recorder.implementation_run

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

    @activity.defn(name="record_signal_finalizer_input_activity")
    async def record_finalizer_input(input: SignalImplementationInput) -> None:
        recorder.finalizer_inputs.append(input)

    # The production self-driving worker runs with the pydantic data converter; the default converter
    # mangles the enum/pydantic payloads these activities exchange (RepoSelectionResult,
    # ActionabilityChoice), sending the workflow down the wrong decision branch.
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SignalReportSummaryWorkflow, StubSignalImplementationFinalizerWorkflow],
            activities=[
                fake_quota,
                fake_fetch,
                fake_has_assigned_signals,
                fake_mark_in_progress,
                fake_safety,
                fake_select_repo,
                fake_research,
                fake_mark_ready,
                fake_publish,
                fake_implementation_buffer,
                fake_autostart,
                fake_revert,
                fake_reset,
                fake_failed,
                record_finalizer_input,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            workflow_inputs = inputs or SignalReportSummaryWorkflowInputs(team_id=1, report_id=str(uuid.uuid4()))
            if signal_during_first_pass:
                recorder.continue_research.clear()
            if legacy_stage_handoffs:
                original_patched = workflow.patched

                def pre_handoff_patched(patch_id: str) -> bool:
                    return False if patch_id == "signals-stage-handoffs-v1" else original_patched(patch_id)

                with patch(f"{SUMMARY_MODULE_PATH}.workflow.patched", side_effect=pre_handoff_patched):
                    handle = await env.client.start_workflow(
                        SignalReportSummaryWorkflow.run,
                        workflow_inputs,
                        id=f"summary-workflow-{uuid.uuid4()}",
                        task_queue=TASK_QUEUE,
                    )
                    await asyncio.wait_for(handle.result(), timeout=30)
            else:
                handle = await env.client.start_workflow(
                    SignalReportSummaryWorkflow.run,
                    workflow_inputs,
                    id=f"summary-workflow-{uuid.uuid4()}",
                    task_queue=TASK_QUEUE,
                )
                if signal_during_first_pass:
                    await asyncio.wait_for(recorder.research_started.wait(), timeout=30)
                    await handle.signal("submit_signal_keys", signal_during_first_pass)
                    recorder.continue_research.set()
                await asyncio.wait_for(handle.result(), timeout=30)
            history = await handle.fetch_history()
            for finalizer_input in recorder.expected_finalizer_inputs:
                await asyncio.wait_for(
                    env.client.get_workflow_handle(
                        SignalImplementationFinalizerWorkflow.workflow_id_for(
                            workflow_inputs.team_id,
                            finalizer_input.signal_key,
                            finalizer_input.additional_signal_keys,
                        )
                    ).result(),
                    timeout=30,
                )
            return history


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
# Signal handoff finalization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handoff_batches_submitted_keys_after_the_first_pass() -> None:
    recorder = _Recorder()
    recorder.expected_finalizer_inputs = [
        SignalImplementationInput(team_id=1, signal_key="first", additional_signal_keys=("covered",)),
    ]
    await _run_summary_workflow(
        recorder,
        SignalReportSummaryWorkflowInputs(
            team_id=1,
            report_id=str(uuid.uuid4()),
            signal_keys=["first", "covered"],
            context_signal_keys=["previous"],
        ),
    )

    assert recorder.safety_signal_keys == ["first"]
    assert recorder.research_signal_keys == ["first"]
    assert recorder.finalizer_inputs == recorder.expected_finalizer_inputs


@pytest.mark.asyncio
async def test_handoff_batches_the_research_trigger_without_implementation() -> None:
    recorder = _Recorder()
    signal_keys = ["research-trigger", *[f"signal-{index}" for index in range(19)]]
    recorder.expected_finalizer_inputs = [
        SignalImplementationInput(
            team_id=1,
            signal_key="research-trigger",
            additional_signal_keys=tuple(signal_keys[1:]),
        ),
    ]
    await _run_summary_workflow(
        recorder,
        SignalReportSummaryWorkflowInputs(team_id=1, report_id=str(uuid.uuid4()), signal_keys=signal_keys),
    )

    assert recorder.research_signal_keys == ["research-trigger"]
    assert recorder.finalizer_inputs == recorder.expected_finalizer_inputs


@pytest.mark.asyncio
async def test_handoff_isolates_implementation_owner_and_batches_other_keys() -> None:
    recorder = _Recorder()
    recorder.actionability_choice = ActionabilityChoice.IMMEDIATELY_ACTIONABLE
    recorder.implementation_run = ImplementationRunRef(task_id="task-1", run_id="run-1")
    signal_keys = ["owner", *[f"non-owner-{index}" for index in range(20)]]
    recorder.expected_finalizer_inputs = [
        SignalImplementationInput(team_id=1, signal_key="owner", task_id="task-1", run_id="run-1"),
        SignalImplementationInput(
            team_id=1,
            signal_key="non-owner-0",
            additional_signal_keys=tuple(signal_keys[2:]),
        ),
    ]

    await _run_summary_workflow(
        recorder,
        SignalReportSummaryWorkflowInputs(team_id=1, report_id=str(uuid.uuid4()), signal_keys=signal_keys),
    )

    assert recorder.research_signal_keys == ["owner"]
    assert recorder.finalizer_inputs == recorder.expected_finalizer_inputs


@pytest.mark.asyncio
async def test_autostart_activity_hands_back_only_the_run_identifiers() -> None:
    report_id = str(uuid.uuid4())
    run = SimpleNamespace(
        id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        state={"sandbox_connect_token": "a-live-sandbox-credential"},
        output={"pr_url": "https://example.com/pr/1"},
    )
    handoff = SimpleNamespace(signal=SimpleNamespace(metadata={"report_id": report_id}))

    with (
        patch(f"{SUMMARY_MODULE_PATH}.read_handoff", AsyncMock(return_value=handoff)),
        patch(
            f"{SUMMARY_MODULE_PATH}.maybe_autostart_from_report_artefacts",
            AsyncMock(return_value=run),
        ) as autostart,
    ):
        result = await ActivityEnvironment().run(
            maybe_autostart_implementation_activity,
            MaybeAutostartImplementationInput(team_id=1, report_id=report_id, signal_key="key-1"),
        )

    assert result == ImplementationRunRef(task_id=str(run.task_id), run_id=str(run.id))
    assert autostart.call_args.kwargs["pending_metadata"] == handoff.signal.metadata


@pytest.mark.asyncio
async def test_finalizer_start_failure_leaves_the_report_alone() -> None:
    inputs = SignalReportSummaryWorkflowInputs(team_id=1, report_id=str(uuid.uuid4()))

    with (
        patch(f"{SUMMARY_MODULE_PATH}.workflow.patched", return_value=True),
        patch(
            f"{SUMMARY_MODULE_PATH}.workflow.start_child_workflow",
            AsyncMock(side_effect=RuntimeError("child start rejected")),
        ),
        patch(f"{SUMMARY_MODULE_PATH}.workflow.logger") as workflow_logger,
    ):
        await SignalReportSummaryWorkflow()._start_signal_finalizer(inputs, "key-1")

    workflow_logger.exception.assert_called_once()


@pytest.mark.parametrize(
    ("pass_completed", "next_bucket", "keys", "metadata", "expected"),
    [
        (
            False,
            None,
            ["late", "early"],
            [
                {"research_trigger": True, "report_signal_count": 4},
                {"research_trigger": True, "report_signal_count": 2},
            ],
            "early",
        ),
        (True, 4, ["midpoint"], [{"research_trigger": False, "report_signal_count": 3}], None),
        (True, 4, ["crossed"], [{"research_trigger": False, "report_signal_count": 4}], "crossed"),
        (True, None, ["promoted"], [{"research_trigger": True, "report_signal_count": 3}], "promoted"),
    ],
)
def test_select_research_signal_key_respects_buckets_and_promoted_owners(
    pass_completed: bool,
    next_bucket: int | None,
    keys: list[str],
    metadata: list[dict],
    expected: str | None,
) -> None:
    signals = [_signal_data() for _ in keys]
    for signal, signal_metadata in zip(signals, metadata):
        signal.metadata = signal_metadata
    result = FetchSignalsForReportOutput(
        signals=signals,
        signal_key_by_id={signal.signal_id: key for signal, key in zip(signals, keys)},
    )

    assert select_research_signal_key(keys, result, pass_completed, next_bucket) == expected


@pytest.mark.asyncio
async def test_handoff_finalizes_a_key_submitted_while_the_first_pass_runs() -> None:
    recorder = _Recorder()
    recorder.expected_finalizer_inputs = [
        SignalImplementationInput(team_id=1, signal_key="first", additional_signal_keys=("covered",)),
        SignalImplementationInput(team_id=1, signal_key="arrived-during-pass"),
    ]
    await _run_summary_workflow(
        recorder,
        SignalReportSummaryWorkflowInputs(
            team_id=1,
            report_id=str(uuid.uuid4()),
            signal_keys=["first", "covered"],
        ),
        signal_during_first_pass=["arrived-during-pass"],
    )

    assert recorder.research_signal_keys == ["first"]
    assert recorder.finalizer_inputs == recorder.expected_finalizer_inputs


@pytest.mark.asyncio
async def test_summary_replays_history_recorded_before_stage_handoffs() -> None:
    history = await _run_summary_workflow(_Recorder(), legacy_stage_handoffs=True)

    await Replayer(
        workflows=[SignalReportSummaryWorkflow],
        workflow_runner=UnsandboxedWorkflowRunner(),
        data_converter=pydantic_data_converter,
    ).replay_workflow(history)


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
