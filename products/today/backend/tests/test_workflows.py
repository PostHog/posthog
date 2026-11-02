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
    PinnedNumber,
    ResolvePinsInputs,
    ResolvePinsResult,
)
from products.today.backend.temporal.workflows import ComputeTodayHighlightsWorkflow


@pytest_asyncio.fixture(scope="module")
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


PINS = [PinnedNumber("insight:a"), PinnedNumber("insight:b", dashboard_id=7)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pins,pins_fail,asked,pinned",
    [
        ([], False, [], "[]"),
        (PINS, False, [["insight:a", "insight:b"]], "found"),
        (PINS, True, [["insight:a", "insight:b"]], "[]"),
    ],
)
async def test_sources_and_pins_are_resolved_once_and_finalized_together(
    environment: WorkflowEnvironment, pins: list[PinnedNumber], pins_fail: bool, asked: list[list[str]], pinned: str
) -> None:
    finalized: list[FinalizeHighlightsInputs] = []
    resolved: list[list[str]] = []

    @activity.defn(name="run_highlight_source_activity")
    async def run_source(inputs: HighlightSourceInputs) -> HighlightSourceResult:
        if inputs.source_name == "broken":
            raise ApplicationError("The source query failed.")
        return HighlightSourceResult(source_name=inputs.source_name, found="{}", failed=False)

    @activity.defn(name="resolve_pins_activity")
    async def resolve_pins(inputs: ResolvePinsInputs) -> ResolvePinsResult:
        resolved.append([pin.key for pin in inputs.pins])
        if pins_fail:
            raise ApplicationError("The pinned query failed.")
        return ResolvePinsResult(found="found")

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
                pins=pins,
            ),
            id=str(uuid.uuid4()),
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        )

    assert (resolved, [(inputs.results, inputs.pins, inputs.pinned) for inputs in finalized]) == (
        asked,
        [
            (
                [
                    HighlightSourceResult(source_name="alerts", found="{}", failed=False),
                    HighlightSourceResult(source_name="broken", found=None, failed=True),
                ],
                pins,
                pinned,
            )
        ],
    )
