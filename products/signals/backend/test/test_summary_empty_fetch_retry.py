import uuid
import asyncio
from datetime import UTC, datetime

import pytest

from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

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
    SignalReportSummaryWorkflow,
)
from products.signals.backend.temporal.types import SignalData, SignalReportSummaryWorkflowInputs

TASK_QUEUE = "test-summary-empty-fetch-retry-queue"


class _Recorder:
    def __init__(self, empty_fetches_before_signal: int) -> None:
        # How many times fake_fetch should return an empty result before returning a real signal.
        # A value >= EMPTY_FETCH_RETRY_ATTEMPTS + 1 means the fetch never recovers.
        self.empty_fetches_before_signal = empty_fetches_before_signal
        self.fetches = 0
        self.marks_in_progress = 0
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
        return False

    @activity.defn(name="fetch_signals_for_report_activity")
    async def fake_fetch(input: FetchSignalsForReportInput) -> FetchSignalsForReportOutput:
        recorder.fetches += 1
        if recorder.fetches <= recorder.empty_fetches_before_signal:
            return FetchSignalsForReportOutput(signals=[])
        return FetchSignalsForReportOutput(signals=[_signal_data()])

    @activity.defn(name="mark_report_in_progress_activity")
    async def fake_mark_in_progress(input: MarkReportInProgressInput) -> None:
        recorder.marks_in_progress += 1

    @activity.defn(name="report_safety_judge_activity")
    async def fake_safety(input: SafetyJudgeInput) -> SafetyJudgeOutput:
        return SafetyJudgeOutput(safe=True, explanation="ok")

    @activity.defn(name="select_repository_activity")
    async def fake_select_repo(input: SelectRepositoryInput) -> RepoSelectionResult:
        return RepoSelectionResult(repository="owner/repo", reason="selected")

    @activity.defn(name="run_agentic_report_activity")
    async def fake_research(input: RunAgenticReportInput) -> RunAgenticReportOutput:
        from products.signals.backend.report_generation.research import ActionabilityChoice

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
    async def fake_revert(input) -> None:  # noqa: ANN001
        pass

    @activity.defn(name="reset_report_to_potential_activity")
    async def fake_reset(input) -> None:  # noqa: ANN001
        pass

    @activity.defn(name="mark_report_failed_activity")
    async def fake_failed(input: MarkReportFailedInput) -> None:
        recorder.failures += 1

    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SignalReportSummaryWorkflow],
            activities=[
                fake_quota,
                fake_fetch,
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
                    id=f"summary-empty-fetch-{uuid.uuid4()}",
                    task_queue=TASK_QUEUE,
                ),
                timeout=30,
            )


@pytest.mark.asyncio
async def test_transient_empty_fetch_retries_instead_of_failing():
    # A signal that lands just after the first read (mirrors ClickHouse insert lag behind an
    # already-confirmed emission) must not be treated as "no signals" — this catches the
    # regression where a single empty read killed the report with no retry.
    recorder = _Recorder(empty_fetches_before_signal=1)
    await _run_summary_workflow(recorder)
    assert recorder.fetches == 2
    assert recorder.failures == 0
    assert recorder.marks_in_progress == 1


@pytest.mark.asyncio
async def test_empty_fetch_still_fails_after_exhausting_retries():
    # If signals genuinely never show up, the retry loop must give up and mark the report
    # failed rather than retry forever.
    recorder = _Recorder(empty_fetches_before_signal=EMPTY_FETCH_RETRY_ATTEMPTS + 1)
    await _run_summary_workflow(recorder)
    assert recorder.fetches == EMPTY_FETCH_RETRY_ATTEMPTS + 1
    assert recorder.failures == 1
    assert recorder.marks_in_progress == 0
