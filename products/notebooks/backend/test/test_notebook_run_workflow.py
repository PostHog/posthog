import uuid

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.notebooks.backend.temporal.notebook_run import NotebookRunWorkflow
from products.notebooks.backend.temporal.notebook_run_inputs import (
    CellDispatched,
    CellRunLookup,
    CellStatus,
    NotebookRunCellInput,
    NotebookRunFinish,
    NotebookRunInput,
)

TEAM_ID = 42


async def _drive(
    dispatch_by_index: dict[int, CellDispatched],
    statuses_by_run: dict[str, list[CellStatus]],
) -> tuple[list[int], list[NotebookRunFinish]]:
    """Run the workflow against fake activities; report which cells it dispatched and how it finished."""
    dispatched: list[int] = []
    finishes: list[NotebookRunFinish] = []

    @activity.defn(name="notebook-run-dispatch-cell")
    async def dispatch(input: NotebookRunCellInput) -> CellDispatched:
        dispatched.append(input.index)
        return dispatch_by_index.get(input.index, CellDispatched(outcome="finished"))

    @activity.defn(name="notebook-run-check-cell")
    async def check(input: CellRunLookup) -> CellStatus:
        remaining = statuses_by_run[input.node_run_id]
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    @activity.defn(name="notebook-run-finish")
    async def finish(input: NotebookRunFinish) -> None:
        finishes.append(input)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[NotebookRunWorkflow],
            activities=[dispatch, check, finish],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await environment.client.execute_workflow(
                NotebookRunWorkflow.run,
                NotebookRunInput(notebook_run_id=str(uuid.uuid4()), team_id=TEAM_ID),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
    return dispatched, finishes


@pytest.mark.asyncio
async def test_cells_run_in_order_and_the_run_ends_done() -> None:
    dispatched, finishes = await _drive(
        {
            0: CellDispatched(outcome="dispatched", node_run_id="r0", node_id="s1"),
            1: CellDispatched(outcome="dispatched", node_run_id="r1", node_id="s2"),
            2: CellDispatched(outcome="dispatched", node_run_id="r2", node_id="p1"),
        },
        {
            "r0": [CellStatus(status="done")],
            "r1": [CellStatus(status="done")],
            "r2": [CellStatus(status="done")],
        },
    )

    assert dispatched == [0, 1, 2, 3]
    assert [(f.status, f.failed_node_id) for f in finishes] == [("done", None)]


@pytest.mark.asyncio
async def test_a_failing_cell_stops_the_cells_after_it() -> None:
    dispatched, finishes = await _drive(
        {
            0: CellDispatched(outcome="dispatched", node_run_id="r0", node_id="s1"),
            1: CellDispatched(outcome="dispatched", node_run_id="r1", node_id="s2"),
            2: CellDispatched(outcome="dispatched", node_run_id="r2", node_id="p1"),
        },
        {
            "r0": [CellStatus(status="done")],
            "r1": [CellStatus(status="failed", error="Unknown table")],
            "r2": [CellStatus(status="done")],
        },
    )

    assert dispatched == [0, 1]
    assert [(f.status, f.failed_node_id, f.error) for f in finishes] == [("failed", "s2", "Unknown table")]


@pytest.mark.asyncio
async def test_an_interrupted_run_stops_before_the_next_dispatch() -> None:
    # The interrupt endpoint already wrote the terminal status, so the workflow must not
    # write a second outcome over it.
    dispatched, finishes = await _drive(
        {
            0: CellDispatched(outcome="dispatched", node_run_id="r0", node_id="s1"),
            1: CellDispatched(outcome="interrupted"),
        },
        {"r0": [CellStatus(status="done")]},
    )

    assert dispatched == [0, 1]
    assert finishes == []


@pytest.mark.asyncio
async def test_a_cell_that_stays_running_is_polled_until_it_finishes() -> None:
    # The direct (pure HogQL) lane only advances when somebody reads the run, so the
    # workflow's poll is the thing that moves it.
    dispatched, finishes = await _drive(
        {0: CellDispatched(outcome="dispatched", node_run_id="r0", node_id="s1")},
        {"r0": [CellStatus(status="running"), CellStatus(status="running"), CellStatus(status="done")]},
    )

    assert dispatched == [0, 1]
    assert [f.status for f in finishes] == ["done"]


@pytest.mark.asyncio
async def test_a_cell_that_cannot_be_dispatched_fails_the_run() -> None:
    dispatched, finishes = await _drive(
        {0: CellDispatched(outcome="failed", node_id="s1", error="Unknown reference 'df'.")},
        {},
    )

    assert dispatched == [0]
    assert [(f.status, f.failed_node_id, f.error) for f in finishes] == [("failed", "s1", "Unknown reference 'df'.")]
