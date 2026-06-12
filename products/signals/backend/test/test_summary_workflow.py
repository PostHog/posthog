import uuid
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeOutput
from products.signals.backend.temporal.signal_queries import FetchSignalsForReportOutput
from products.signals.backend.temporal.summary import SignalReportSummaryWorkflow
from products.signals.backend.temporal.types import SignalData, SignalReportSummaryWorkflowInputs

TASK_QUEUE = "test-summary-workflow-queue"


def _signal() -> SignalData:
    return SignalData(
        signal_id=str(uuid.uuid4()),
        content="something is broken",
        source_product="error_tracking",
        source_type="issue",
        source_id="issue-1",
        weight=1.0,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )


class _Recorder:
    def __init__(self, fetch_results: list[list[SignalData]]) -> None:
        # One entry per fetch call; the last entry is reused if fetched more times.
        self._fetch_results = fetch_results
        self.fetch_calls = 0
        self.in_progress_calls = 0
        self.pending_input_calls = 0
        self.failed_calls = 0
        self.deferred_calls = 0

    def next_fetch(self) -> list[SignalData]:
        result = self._fetch_results[min(self.fetch_calls, len(self._fetch_results) - 1)]
        self.fetch_calls += 1
        return result


async def _run_workflow(recorder: _Recorder) -> None:
    @activity.defn(name="fetch_signals_for_report_activity")
    async def fake_fetch(_input) -> FetchSignalsForReportOutput:
        return FetchSignalsForReportOutput(signals=recorder.next_fetch())

    @activity.defn(name="defer_report_signals_not_ready_activity")
    async def fake_defer(_input) -> None:
        recorder.deferred_calls += 1

    @activity.defn(name="mark_report_failed_activity")
    async def fake_failed(_input) -> None:
        recorder.failed_calls += 1

    @activity.defn(name="mark_report_in_progress_activity")
    async def fake_in_progress(_input) -> None:
        recorder.in_progress_calls += 1

    @activity.defn(name="report_safety_judge_activity")
    async def fake_safety(_input) -> SafetyJudgeOutput:
        return SafetyJudgeOutput(safe=True, explanation=None)

    @activity.defn(name="select_repository_activity")
    async def fake_select_repo(_input) -> RepoSelectionResult:
        # repository=None drives the workflow down the REQUIRES_HUMAN_INPUT branch, which keeps
        # the test path short (no agentic run, no inbox notification) while still proving the
        # workflow proceeded past the empty-fetch guard.
        return RepoSelectionResult(repository=None, reason="no candidate")

    @activity.defn(name="mark_report_pending_input_activity")
    async def fake_pending_input(_input) -> None:
        recorder.pending_input_calls += 1

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SignalReportSummaryWorkflow],
            activities=[
                fake_fetch,
                fake_defer,
                fake_failed,
                fake_in_progress,
                fake_safety,
                fake_select_repo,
                fake_pending_input,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                SignalReportSummaryWorkflow.run,
                SignalReportSummaryWorkflowInputs(team_id=1, report_id=str(uuid.uuid4())),
                id=f"summary-wf-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )


@pytest.mark.asyncio
async def test_empty_then_ready_fetch_proceeds_after_retry():
    # First fetch is empty (ingestion lag), the retry finds the signals.
    recorder = _Recorder([[], [_signal()]])
    await _run_workflow(recorder)

    assert recorder.fetch_calls == 2  # initial empty fetch + one retry that succeeds
    assert recorder.in_progress_calls == 1  # proceeded past the empty-fetch guard
    assert recorder.pending_input_calls == 1
    assert recorder.failed_calls == 0
    assert recorder.deferred_calls == 0


@pytest.mark.asyncio
async def test_permanently_empty_fetch_defers_without_failing():
    recorder = _Recorder([[]])  # always empty
    await _run_workflow(recorder)

    assert recorder.fetch_calls == 4  # initial fetch + 3 durable-sleep retries
    assert recorder.deferred_calls == 1
    assert recorder.failed_calls == 0  # must NOT mark the report failed
    assert recorder.in_progress_calls == 0


@pytest.mark.asyncio
async def test_patched_off_marks_failed_on_empty_fetch():
    # Simulate a run started before the patch: workflow.patched returns False, so the legacy
    # mark-failed branch must still run for deterministic replay.
    real_patched = workflow.patched

    def selective_patched(patch_id: str) -> bool:
        if patch_id == "signals-retry-fetch-on-empty":
            return False
        return real_patched(patch_id)

    recorder = _Recorder([[]])
    with patch("temporalio.workflow.patched", side_effect=selective_patched):
        await _run_workflow(recorder)

    assert recorder.fetch_calls == 1  # no retries on the legacy path
    assert recorder.failed_calls == 1
    assert recorder.deferred_calls == 0
