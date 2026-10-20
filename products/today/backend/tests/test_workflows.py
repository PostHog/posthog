import uuid
from collections.abc import AsyncIterator

import pytest

from django.conf import settings

import pytest_asyncio
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.today.backend.temporal.inputs import (
    HIGHLIGHTS_WORKFLOW_NAME,
    ComputeHighlightsInputs,
    FinalizeHighlightsInputs,
    HighlightSourceInputs,
    HighlightSourceResult,
)
from products.today.backend.temporal.workflows import ComputeTodayHighlightsWorkflow


@pytest_asyncio.fixture(scope="module")
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


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
