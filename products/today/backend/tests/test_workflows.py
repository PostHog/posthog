import uuid
from collections.abc import AsyncIterator

import pytest

from django.conf import settings

import pytest_asyncio
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.today.backend.logic.generate import ATTEMPTS
from products.today.backend.temporal.inputs import (
    GENERATE_WORKFLOW_NAME,
    HIGHLIGHTS_WORKFLOW_NAME,
    ComputeHighlightsInputs,
    FinalizeHighlightsInputs,
    GenerateBriefingInputs,
    HighlightSourceInputs,
    HighlightSourceResult,
    MarkFailedInputs,
)
from products.today.backend.temporal.workflows import ComputeTodayHighlightsWorkflow, GenerateTodayBriefingWorkflow


@pytest_asyncio.fixture(scope="module")
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.mark.asyncio
async def test_a_failing_attempt_is_retried_then_marks_the_briefing_failed_once(
    environment: WorkflowEnvironment,
) -> None:
    attempts = 0
    marked_failed: list[MarkFailedInputs] = []

    @activity.defn(name="run_agent_activity")
    async def write_briefing(inputs: GenerateBriefingInputs) -> None:
        nonlocal attempts
        attempts += 1
        raise ApplicationError("The LLM reply was not a briefing.")

    @activity.defn(name="mark_failed_activity")
    async def mark_failed(inputs: MarkFailedInputs) -> None:
        marked_failed.append(inputs)

    async with Worker(
        environment.client,
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        workflows=[GenerateTodayBriefingWorkflow],
        activities=[write_briefing, mark_failed],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await environment.client.execute_workflow(
            GENERATE_WORKFLOW_NAME,
            GenerateBriefingInputs(team_id=1, briefing_id="b-1"),
            id=str(uuid.uuid4()),
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        )

    assert attempts == ATTEMPTS
    assert [failed.error for failed in marked_failed] == ["The LLM reply was not a briefing."]


@pytest.mark.asyncio
async def test_a_source_that_keeps_failing_is_finalized_as_failed_with_the_others(
    environment: WorkflowEnvironment,
) -> None:
    finalized: list[FinalizeHighlightsInputs] = []

    @activity.defn(name="run_highlight_source_activity")
    async def run_source(inputs: HighlightSourceInputs) -> HighlightSourceResult:
        if inputs.source_name == "broken":
            raise ApplicationError("The source query failed.")
        return HighlightSourceResult(source_name=inputs.source_name, found="{}", failed=False)

    @activity.defn(name="finalize_highlights_activity")
    async def finalize(inputs: FinalizeHighlightsInputs) -> None:
        finalized.append(inputs)

    async with Worker(
        environment.client,
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        workflows=[ComputeTodayHighlightsWorkflow],
        activities=[run_source, finalize],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await environment.client.execute_workflow(
            HIGHLIGHTS_WORKFLOW_NAME,
            ComputeHighlightsInputs(
                team_id=1,
                user_id=2,
                highlights_id="h-1",
                local_day="2026-10-13",
                scopes=None,
                source_names=["alerts", "broken"],
            ),
            id=str(uuid.uuid4()),
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        )

    assert [inputs.results for inputs in finalized] == [
        [
            HighlightSourceResult(source_name="alerts", found="{}", failed=False),
            HighlightSourceResult(source_name="broken", found=None, failed=True),
        ]
    ]
