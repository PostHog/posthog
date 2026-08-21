import uuid

import pytest
from unittest.mock import patch

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Team

from products.signals.backend.report_canvas import ReportCanvasGeneration
from products.signals.backend.temporal.report_canvas import (
    ReportCanvasWorkflowInput,
    SignalReportCanvasWorkflow,
    report_canvases_enabled_activity,
)

TASK_QUEUE = "test-report-canvas"


@pytest.mark.asyncio
async def test_report_canvas_gate_treats_deleted_team_as_disabled() -> None:
    with patch("products.signals.backend.temporal.report_canvas.Team.objects.get", side_effect=Team.DoesNotExist):
        assert await report_canvases_enabled_activity(123) is False


@pytest.mark.asyncio
async def test_workflow_rechecks_the_fingerprint_after_generation() -> None:
    generation = ReportCanvasGeneration(
        canvas_id=uuid.uuid4(),
        discussion_task_id=uuid.uuid4(),
        generation_task_id=uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        fingerprint="a" * 64,
    )
    start_calls = 0

    @activity.defn(name="start_report_canvas_generation_activity")
    async def start_mock(input: ReportCanvasWorkflowInput) -> ReportCanvasGeneration:
        nonlocal start_calls
        start_calls += 1
        if start_calls == 1:
            return generation
        return ReportCanvasGeneration(
            canvas_id=generation.canvas_id,
            discussion_task_id=generation.discussion_task_id,
            generation_task_id=generation.generation_task_id,
            generation_run_id=None,
            fingerprint=generation.fingerprint,
            skipped=True,
        )

    @activity.defn(name="poll_report_canvas_generation_activity")
    async def poll_mock(input: ReportCanvasWorkflowInput, current: ReportCanvasGeneration) -> bool:
        return True

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=TASK_QUEUE,
            workflows=[SignalReportCanvasWorkflow],
            activities=[start_mock, poll_mock],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await environment.client.execute_workflow(
                SignalReportCanvasWorkflow.run,
                ReportCanvasWorkflowInput(team_id=1, report_id=str(uuid.uuid4())),
                id=str(uuid.uuid4()),
                task_queue=TASK_QUEUE,
            )

    assert result is True
    assert start_calls == 2


@pytest.mark.asyncio
async def test_workflow_succeeds_after_three_changed_fingerprints() -> None:
    generation = ReportCanvasGeneration(
        canvas_id=uuid.uuid4(),
        discussion_task_id=uuid.uuid4(),
        generation_task_id=uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        fingerprint="a" * 64,
    )
    start_calls = 0

    @activity.defn(name="start_report_canvas_generation_activity")
    async def start_mock(input: ReportCanvasWorkflowInput) -> ReportCanvasGeneration:
        nonlocal start_calls
        start_calls += 1
        return generation

    @activity.defn(name="poll_report_canvas_generation_activity")
    async def poll_mock(input: ReportCanvasWorkflowInput, current: ReportCanvasGeneration) -> bool:
        return True

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=TASK_QUEUE,
            workflows=[SignalReportCanvasWorkflow],
            activities=[start_mock, poll_mock],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await environment.client.execute_workflow(
                SignalReportCanvasWorkflow.run,
                ReportCanvasWorkflowInput(team_id=1, report_id=str(uuid.uuid4())),
                id=str(uuid.uuid4()),
                task_queue=TASK_QUEUE,
            )

    assert result is True
    assert start_calls == 3
