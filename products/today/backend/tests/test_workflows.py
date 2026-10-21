import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

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
    ResolvePinsInputs,
    ResolvePinsResult,
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

    @activity.defn(name="resolve_pins_activity")
    async def resolve_pins(inputs: ResolvePinsInputs) -> ResolvePinsResult:
        return ResolvePinsResult(keys=[], found="[]", pending=[], failed=False)

    @activity.defn(name="finalize_highlights_activity")
    async def finalize(inputs: FinalizeHighlightsInputs) -> None:
        finalized.append(inputs)

    async with Worker(
        environment.client,
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        workflows=[ComputeTodayHighlightsWorkflow],
        activities=[run_source, resolve_pins, finalize],
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


@pytest.mark.asyncio
async def test_pins_still_computing_are_retried_on_a_timer_and_finalized_together(
    environment: WorkflowEnvironment,
) -> None:
    finalized: list[FinalizeHighlightsInputs] = []
    asked: list[list[str] | None] = []

    @activity.defn(name="run_highlight_source_activity")
    async def run_source(inputs: HighlightSourceInputs) -> HighlightSourceResult:
        return HighlightSourceResult(source_name=inputs.source_name, found="{}", failed=False)

    @activity.defn(name="resolve_pins_activity")
    async def resolve_pins(inputs: ResolvePinsInputs) -> ResolvePinsResult:
        asked.append(inputs.keys)
        if inputs.keys is None:
            return ResolvePinsResult(
                keys=["insight:a", "insight:slow"], found="[]", pending=["insight:slow"], failed=False
            )
        return ResolvePinsResult(keys=["insight:slow"], found="[]", pending=[], failed=False)

    @activity.defn(name="finalize_highlights_activity")
    async def finalize(inputs: FinalizeHighlightsInputs) -> None:
        finalized.append(inputs)

    async with Worker(
        environment.client,
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        workflows=[ComputeTodayHighlightsWorkflow],
        activities=[run_source, resolve_pins, finalize],
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
                source_names=["alerts"],
            ),
            id=str(uuid.uuid4()),
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            execution_timeout=timedelta(minutes=5),
        )

    assert (asked, [[result.pending for result in inputs.pins] for inputs in finalized]) == (
        [None, ["insight:slow"]],
        [[["insight:slow"], []]],
    )
