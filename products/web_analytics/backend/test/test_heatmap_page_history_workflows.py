import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.web_analytics.backend.temporal.page_history.types import (
    CaptureInputs,
    ClaimedCapture,
    DueCapture,
    FinishInputs,
    RenderOutcome,
    TickInputs,
    TickResult,
    capture_workflow_id,
)
from products.web_analytics.backend.temporal.page_history.workflows import (
    HeatmapPageHistoryCaptureWorkflow,
    HeatmapPageHistoryTickWorkflow,
)


class FakeActivities:
    def __init__(self, claim_id: str | None, render: RenderOutcome | Exception, due: list[DueCapture]) -> None:
        self.claim_id = claim_id
        self.render = render
        self.due = due
        self.finished: list[FinishInputs] = []

    def activities(self) -> list:
        @activity.defn(name="heatmap-page-history-claim")
        async def claim(inputs: CaptureInputs) -> str | None:
            return self.claim_id

        @activity.defn(name="heatmap-page-history-render")
        async def render(capture: ClaimedCapture) -> RenderOutcome:
            if isinstance(self.render, Exception):
                raise self.render
            return self.render

        @activity.defn(name="heatmap-page-history-finish")
        async def finish(inputs: FinishInputs) -> None:
            self.finished.append(inputs)

        @activity.defn(name="heatmap-page-history-prune")
        async def prune() -> int:
            return 3

        @activity.defn(name="heatmap-page-history-schedule")
        async def schedule() -> list[DueCapture]:
            return self.due

        return [claim, render, finish, prune, schedule]


async def run_capture(client: Client, task_queue: str, request_id: str) -> str:
    return await client.execute_workflow(
        HeatmapPageHistoryCaptureWorkflow.run,
        CaptureInputs(team_id=1, request_id=request_id),
        id=capture_workflow_id(request_id),
        task_queue=task_queue,
    )


PAGE_NOT_FOUND = RenderOutcome(failure_cause="page_http_status", page_status=404)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim_id,render,result,finished",
    [
        (None, RenderOutcome(), "skipped", None),
        ("claim", RenderOutcome(has_thumbnail=True), "succeeded", RenderOutcome(has_thumbnail=True)),
        ("claim", PAGE_NOT_FOUND, "failed", PAGE_NOT_FOUND),
        (
            "claim",
            ApplicationError("hung", non_retryable=True),
            "failed",
            RenderOutcome(failure_cause="render_timeout"),
        ),
    ],
)
async def test_capture_workflow_publishes_or_records_the_failure(
    claim_id: str | None, render: RenderOutcome | Exception, result: str, finished: RenderOutcome | None
) -> None:
    fakes = FakeActivities(claim_id, render, [])
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[HeatmapPageHistoryCaptureWorkflow],
            activities=fakes.activities(),
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            assert await run_capture(env.client, task_queue, str(uuid.uuid4())) == result
    assert [inputs.outcome for inputs in fakes.finished] == ([finished] if finished else [])


@pytest.mark.asyncio
async def test_tick_starts_each_due_capture_once() -> None:
    running = str(uuid.uuid4())
    due = [
        DueCapture(team_id=1, request_id=str(uuid.uuid4()), seconds_left=600),
        DueCapture(team_id=1, request_id=running, seconds_left=600),
        DueCapture(team_id=1, request_id=str(uuid.uuid4()), seconds_left=0),
    ]
    fakes = FakeActivities("claim", RenderOutcome(), due)
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[HeatmapPageHistoryCaptureWorkflow, HeatmapPageHistoryTickWorkflow],
            activities=fakes.activities(),
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.start_workflow(
                HeatmapPageHistoryCaptureWorkflow.run,
                CaptureInputs(team_id=1, request_id=running),
                id=capture_workflow_id(running),
                task_queue=str(uuid.uuid4()),
            )
            result = await env.client.execute_workflow(
                HeatmapPageHistoryTickWorkflow.run, TickInputs(), id=str(uuid.uuid4()), task_queue=task_queue
            )
    assert result == TickResult(pruned=3, started=1, already_running=1)
