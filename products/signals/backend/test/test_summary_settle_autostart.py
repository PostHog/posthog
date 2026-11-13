import uuid
import random
import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import AsyncMock, patch

from django.conf import settings
from django.utils import timezone

import pytest_asyncio
from asgiref.sync import sync_to_async
from kombu.exceptions import OperationalError as KombuOperationalError
from temporalio import activity, workflow
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization, Team

from products.signals.backend.github_optional import RepositoryAccessTemporarilyUnavailable
from products.signals.backend.models import SignalReport, SignalTeamConfig
from products.signals.backend.report_generation.research import ActionabilityChoice, Priority
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.tasks import retry_inbox_report_ready_event
from products.signals.backend.temporal.agentic.report import RunAgenticReportInput, RunAgenticReportOutput
from products.signals.backend.temporal.agentic.select_repository import SelectRepositoryInput
from products.signals.backend.temporal.inbox_notification import (
    InboxNotificationInput,
    SignalReportInboxNotificationWorkflow,
)
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeInput, SafetyJudgeOutput
from products.signals.backend.temporal.signal_queries import FetchSignalsForReportInput, FetchSignalsForReportOutput
from products.signals.backend.temporal.summary import (
    CheckReportQuotaGateInput,
    EmitInboxReportReadyInput,
    ImplementationBufferInput,
    MarkReportInProgressInput,
    MarkReportReadyInput,
    MaybeAutostartImplementationInput,
    PublishReportCompletedInput,
    ReportIsCandidateInput,
    SignalReportSummaryWorkflow,
    emit_inbox_report_ready_activity,
    implementation_buffer_seconds_activity,
    mark_report_ready_activity,
    maybe_autostart_implementation_activity,
    report_is_candidate_activity,
)
from products.signals.backend.temporal.types import SignalData, SignalReportSummaryWorkflowInputs
from products.signals.backend.test.inbox_report_events_recorder import (
    inbox_report_ready_events,
    recorded_internal_events,
)

SUMMARY_MODULE_PATH = "products.signals.backend.temporal.summary"
# The settle branch starts the inbox-notification child on VIDEO_EXPORT_TASK_QUEUE; run the worker
# on that same queue so the stub child completes. Otherwise the child stays pending on an unpolled
# queue and the test server's automatic time-skipping never advances past the buffer timer.
TASK_QUEUE = settings.VIDEO_EXPORT_TASK_QUEUE


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_after", [None, 300])
async def test_autostart_preserves_repository_retry_delay(retry_after: int | None) -> None:
    with (
        patch(
            f"{SUMMARY_MODULE_PATH}.maybe_autostart_from_report_artefacts",
            new=AsyncMock(side_effect=RepositoryAccessTemporarilyUnavailable(wait=retry_after)),
        ),
        pytest.raises(ApplicationError) as raised,
    ):
        await ActivityEnvironment().run(
            maybe_autostart_implementation_activity, MaybeAutostartImplementationInput(team_id=1, report_id="report")
        )
    assert raised.value.next_retry_delay == (timedelta(seconds=retry_after) if retry_after else None)


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"SettleAutostartOrg-{random.randint(1, 99999)}",
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SettleAutostartTeam-{random.randint(1, 99999)}",
    )
    yield team
    await sync_to_async(team.delete)()


# ---------------------------------------------------------------------------
# implementation_buffer_seconds_activity: the 24h new-self-driving carve-out
# ---------------------------------------------------------------------------


async def _set_config_created_at(team_id: int, created_at: datetime) -> None:
    # created_at is auto_now_add, so it can't be set on create — update it directly.
    await SignalTeamConfig.objects.aget_or_create(team_id=team_id)
    await SignalTeamConfig.objects.filter(team_id=team_id).aupdate(created_at=created_at)


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "name,configured_seconds,config_age,expected",
    [
        # Buffer disabled globally: no wait for anyone, regardless of org age.
        ("disabled", 0, timedelta(days=30), 0),
        # Org new to self-driving (config younger than the 24h grace): no wait.
        ("new_org", 120, timedelta(hours=1), 0),
        # Established org (config older than the grace): the configured buffer applies.
        ("established_org", 120, timedelta(days=2), 120),
    ],
)
async def test_implementation_buffer_carve_out(ateam, name, configured_seconds, config_age, expected):
    await _set_config_created_at(ateam.id, timezone.now() - config_age)

    with patch(f"{SUMMARY_MODULE_PATH}.IMPLEMENTATION_DEBOUNCE_SECONDS", configured_seconds):
        result = await implementation_buffer_seconds_activity(ImplementationBufferInput(team_id=ateam.id))

    assert result == expected


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_implementation_buffer_applies_when_no_config_row(ateam):
    # A team with no signals config row is not "new to self-driving", so the buffer still applies.
    await SignalTeamConfig.objects.filter(team_id=ateam.id).adelete()

    with patch(f"{SUMMARY_MODULE_PATH}.IMPLEMENTATION_DEBOUNCE_SECONDS", 120):
        result = await implementation_buffer_seconds_activity(ImplementationBufferInput(team_id=ateam.id))

    assert result == 120


# ---------------------------------------------------------------------------
# Workflow: implementation starts at settle, after the buffer, and re-loops
# instead of implementing a stale summary when a signal lands during the wait.
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self, buffer_seconds: int, candidate_on_first_check: bool) -> None:
        self.buffer_seconds = buffer_seconds
        self.candidate_on_first_check = candidate_on_first_check
        self.researches = 0
        self.autostarts = 0
        self.spend_owners: list[str | None] = []
        self.work_owners: list[str | None] = []
        self.candidate_checks = 0
        self.ready_result: bool | None = False
        self.real_ready_transition = False
        self.publications = 0
        # Auto-starts completed by the time the notification child made its first state check. The
        # child only waits for the implementation PR if the task already exists then, so a 0 here
        # means the card ships without the PR link.
        self.autostarts_at_notification: list[int] = []
        self.autostart_inputs: list[MaybeAutostartImplementationInput] = []


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


# The deferred-notification branch starts this child workflow by name; a stub stands in for it so
# the child can start without wiring its activities. The one activity it does run mirrors the real
# child's first state check, which is what decides whether it waits for the implementation PR.
@workflow.defn(name="signal-report-inbox-notification")
class _StubInboxNotificationWorkflow:
    @workflow.run
    async def run(self, input: InboxNotificationInput) -> None:
        await workflow.execute_activity(
            "record_notification_check_activity",
            input,
            start_to_close_timeout=timedelta(seconds=10),
        )


async def _run_summary_workflow(
    recorder: _Recorder,
    *,
    requested_user_id: int | None = None,
    requested_after_run_count: int | None = None,
    team_id: int = 1,
    report_id: str | None = None,
    emit_ready: Callable[[EmitInboxReportReadyInput], Awaitable[None]] | None = None,
) -> None:
    workflow_report_id = report_id or str(uuid.uuid4())

    @activity.defn(name="check_report_quota_gate_activity")
    async def fake_quota(input: CheckReportQuotaGateInput) -> bool:
        # Simulate the limit being crossed during the first pass. Any further stage or
        # buffered research must carry the original admission through implementation.
        if recorder.researches > 0:
            assert input.admitted
        return False

    @activity.defn(name="fetch_signals_for_report_activity")
    async def fake_fetch(input: FetchSignalsForReportInput) -> FetchSignalsForReportOutput:
        return FetchSignalsForReportOutput(signals=[_signal_data()])

    @activity.defn(name="report_spend_owner_activity")
    async def fake_spend_owner(input: SignalReportSummaryWorkflowInputs) -> str:
        return str(uuid.UUID(int=recorder.researches + 1))

    @activity.defn(name="mark_report_in_progress_activity")
    async def fake_mark_in_progress(input: MarkReportInProgressInput) -> None:
        if recorder.real_ready_transition:
            await SignalReport.objects.filter(id=workflow_report_id, status=SignalReport.Status.CANDIDATE).aupdate(
                status=SignalReport.Status.IN_PROGRESS
            )

    @activity.defn(name="report_safety_judge_activity")
    async def fake_safety(input: SafetyJudgeInput) -> SafetyJudgeOutput:
        recorder.work_owners.append(input.signal_id)
        return SafetyJudgeOutput(safe=True, explanation="ok")

    @activity.defn(name="select_repository_activity")
    async def fake_select_repo(input: SelectRepositoryInput) -> RepoSelectionResult:
        recorder.work_owners.append(input.signal_id)
        return RepoSelectionResult(repository="owner/repo", reason="selected")

    @activity.defn(name="github_optional_pilot_activity")
    async def fake_research_access(team_id: int) -> bool:
        return False

    @activity.defn(name="run_agentic_report_activity")
    async def fake_research(input: RunAgenticReportInput) -> RunAgenticReportOutput:
        recorder.work_owners.append(input.signal_id)
        recorder.researches += 1
        return RunAgenticReportOutput(
            title=f"Research {recorder.researches}",
            summary="s",
            choice=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
            priority=Priority.P1,
            explanation="e",
            already_addressed=False,
            repository="owner/repo",
        )

    @activity.defn(name="mark_report_ready_activity")
    async def fake_mark_ready(input: MarkReportReadyInput) -> bool | None:
        # No new signals arrived during the run itself; the buffer is what catches late signals.
        if recorder.real_ready_transition:
            recorder.ready_result = await mark_report_ready_activity(input)
        return recorder.ready_result

    @activity.defn(name="publish_report_completed_activity")
    async def fake_publish(input: PublishReportCompletedInput) -> None:
        recorder.publications += 1

    @activity.defn(name="publish_report_spend_activity")
    async def fake_publish_spend(input: SignalReportSummaryWorkflowInputs) -> None:
        recorder.spend_owners.append(input.signal_id)

    @activity.defn(name="check_report_task_settlement_activity")
    async def fake_task_settlement(input: SignalReportSummaryWorkflowInputs) -> None:
        return None

    @activity.defn(name="implementation_buffer_seconds_activity")
    async def fake_buffer(input: ImplementationBufferInput) -> int:
        if recorder.real_ready_transition and recorder.candidate_on_first_check and recorder.researches == 1:
            await SignalReport.objects.filter(id=workflow_report_id).aupdate(status=SignalReport.Status.CANDIDATE)
        return recorder.buffer_seconds

    @activity.defn(name="report_is_candidate_activity")
    async def fake_candidate(input: ReportIsCandidateInput) -> bool:
        recorder.candidate_checks += 1
        if recorder.real_ready_transition:
            return await report_is_candidate_activity(input)
        return recorder.candidate_on_first_check and recorder.candidate_checks == 1

    @activity.defn(name="maybe_autostart_implementation_activity")
    async def fake_autostart(input: MaybeAutostartImplementationInput) -> None:
        recorder.autostarts += 1
        recorder.autostart_inputs.append(input)

    @activity.defn(name="emit_inbox_report_ready_activity")
    async def fake_emit_ready(input: EmitInboxReportReadyInput) -> None:
        return None

    @activity.defn(name="record_notification_check_activity")
    async def fake_notification_check(input: InboxNotificationInput) -> None:
        recorder.autostarts_at_notification.append(recorder.autostarts)

    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SignalReportSummaryWorkflow, _StubInboxNotificationWorkflow],
            activities=[
                fake_quota,
                fake_fetch,
                fake_mark_in_progress,
                fake_spend_owner,
                fake_safety,
                fake_select_repo,
                fake_research_access,
                fake_research,
                fake_mark_ready,
                fake_publish,
                fake_publish_spend,
                fake_task_settlement,
                fake_buffer,
                fake_candidate,
                fake_autostart,
                fake_notification_check,
                emit_ready or fake_emit_ready,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await asyncio.wait_for(
                env.client.execute_workflow(
                    SignalReportSummaryWorkflow.run,
                    SignalReportSummaryWorkflowInputs(
                        team_id=team_id,
                        report_id=workflow_report_id,
                        requested_implementation_user_id=requested_user_id,
                        requested_after_run_count=requested_after_run_count,
                    ),
                    id=f"summary-settle-{uuid.uuid4()}",
                    task_queue=TASK_QUEUE,
                ),
                timeout=30,
            )
            # The notification child is detached (ABANDON), so it can outlive the parent; wait for
            # it before asserting on what it saw.
            if recorder.ready_result is not None:
                await asyncio.wait_for(
                    env.client.get_workflow_handle(
                        SignalReportInboxNotificationWorkflow.workflow_id_for(team_id, workflow_report_id)
                    ).result(),
                    timeout=30,
                )


@pytest.mark.asyncio
async def test_skipped_ready_does_not_settle():
    recorder = _Recorder(buffer_seconds=0, candidate_on_first_check=False)
    recorder.ready_result = None
    await _run_summary_workflow(recorder)
    assert recorder.researches == 1
    assert recorder.publications == 0
    assert recorder.autostarts == 0
    assert recorder.autostarts_at_notification == []


@pytest.mark.asyncio
async def test_no_buffer_autostarts_immediately_at_settle():
    recorder = _Recorder(buffer_seconds=0, candidate_on_first_check=False)
    await _run_summary_workflow(recorder)
    # With the buffer disabled, implementation starts right at settle: no candidate re-check, one run.
    assert recorder.researches == 1
    assert recorder.candidate_checks == 0
    assert recorder.autostarts == 1
    # The task exists before the notification looks, so its card can wait for the PR.
    assert recorder.autostarts_at_notification == [1]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "status_at_start,buffer_seconds,signal_during_buffer,expected_titles",
    [
        (SignalReport.Status.CANDIDATE, 0, False, ["Research 1"]),
        (SignalReport.Status.CANDIDATE, 120, True, ["Research 2"]),
        (SignalReport.Status.SUPPRESSED, 0, False, []),
    ],
    ids=["settled", "re-researched_during_buffer", "suppressed_during_research"],
)
async def test_only_the_settled_summary_reaches_destinations(
    ateam, status_at_start, buffer_seconds, signal_during_buffer, expected_titles
):
    report = await SignalReport.objects.acreate(
        team=ateam, status=status_at_start, title="Before research", summary="Summary"
    )
    recorder = _Recorder(buffer_seconds=buffer_seconds, candidate_on_first_check=signal_during_buffer)
    recorder.real_ready_transition = True

    with recorded_internal_events() as (sent, _):
        await _run_summary_workflow(
            recorder, team_id=ateam.id, report_id=str(report.id), emit_ready=emit_inbox_report_ready_activity
        )

    assert [
        (event["report_id"], event["title"], event["source_products"]) for event in inbox_report_ready_events(sent)
    ] == [(str(report.id), title, ["error_tracking"]) for title in expected_titles]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_ready_event_that_is_neither_sent_nor_queued_fails_for_temporal_to_retry(ateam):
    with (
        recorded_internal_events() as (sent, _),
        patch.object(retry_inbox_report_ready_event, "apply_async", side_effect=KombuOperationalError("broker down")),
        pytest.raises(RuntimeError),
    ):
        await ActivityEnvironment().run(
            emit_inbox_report_ready_activity,
            EmitInboxReportReadyInput(team_id=ateam.id, report_id="not-a-report-id", source_products=["scout"]),
        )

    assert sent == []


@pytest.mark.asyncio
async def test_requested_implementation_reaches_settle_after_fresh_research():
    recorder = _Recorder(buffer_seconds=0, candidate_on_first_check=False)
    await _run_summary_workflow(recorder, requested_user_id=42, requested_after_run_count=5)
    assert recorder.researches == 1
    assert len(recorder.autostart_inputs) == 1
    assert recorder.autostart_inputs[0].requested_user_id == 42
    assert recorder.autostart_inputs[0].requested_after_run_count == 5


@pytest.mark.asyncio
async def test_buffer_autostarts_when_no_signal_arrives():
    recorder = _Recorder(buffer_seconds=120, candidate_on_first_check=False)
    await _run_summary_workflow(recorder)
    # The buffer elapses, the report is still settled (not candidate), so implementation starts once.
    assert recorder.researches == 1
    assert recorder.candidate_checks == 1
    assert recorder.autostarts == 1
    assert recorder.autostarts_at_notification == [1]


@pytest.mark.asyncio
async def test_signal_during_buffer_re_researches_instead_of_implementing():
    recorder = _Recorder(buffer_seconds=120, candidate_on_first_check=True)
    await _run_summary_workflow(recorder)
    # A signal landed during the buffer (report back to candidate), so the run loops to re-research
    # rather than implementing the now-stale summary; implementation only starts after it settles again.
    assert recorder.researches == 2
    assert recorder.spend_owners == [str(uuid.UUID(int=1)), str(uuid.UUID(int=2))]
    assert recorder.work_owners == [str(uuid.UUID(int=1))] * 3 + [str(uuid.UUID(int=2))] * 3
    assert recorder.candidate_checks == 2
    assert recorder.autostarts == 1
    # Only the settled run notifies, so no card goes out for the summary the re-research replaced.
    assert recorder.autostarts_at_notification == [1]
