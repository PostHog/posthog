import uuid

import pytest

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.notebooks.backend.models import NotebookNodeRun, NotebookRun
from products.notebooks.backend.temporal.notebook_run import (
    NotebookRunCellCheckInput,
    NotebookRunCellInput,
    NotebookRunFinishInput,
    NotebookRunInput,
    NotebookRunWorkflow,
)


class _Recorder:
    """Stand-ins for the five activities, so the tests are about the loop, not the database."""

    def __init__(
        self,
        *,
        cell_statuses: dict[int, list[str]] | None = None,
        run_statuses: list[str] | None = None,
        fail_dispatch: bool = False,
    ) -> None:
        self.cell_statuses = cell_statuses or {}
        self.run_statuses = list(run_statuses or [])
        self.run_status: str = NotebookRun.Status.RUNNING
        self.fail_dispatch = fail_dispatch
        self.running: set[str] = set()
        self.dispatched: list[int] = []
        self.finished: list[NotebookRunFinishInput] = []
        self.checks: list[str] = []
        self.advanced: list[int] = []
        self.stopped = 0
        self._pending: dict[str, list[str]] = {}

    def activities(self) -> list:
        recorder = self

        @activity.defn(name="notebook-run-read-status")
        async def read_status(input: NotebookRunInput) -> str:
            if recorder.run_statuses:
                recorder.run_status = recorder.run_statuses.pop(0)
            return recorder.run_status

        @activity.defn(name="notebook-run-advance")
        async def advance(input: NotebookRunCellInput) -> None:
            recorder.advanced.append(input.index)

        @activity.defn(name="notebook-run-dispatch-cell")
        async def dispatch_cell(input: NotebookRunCellInput) -> str:
            recorder.dispatched.append(input.index)
            node_run_id = f"run-{input.index}"
            recorder.running.add(node_run_id)
            recorder._pending[node_run_id] = list(
                recorder.cell_statuses.get(input.index, [NotebookNodeRun.Status.DONE])
            )
            if recorder.fail_dispatch:
                raise ApplicationError("Dispatch acknowledgement lost")
            return node_run_id

        @activity.defn(name="notebook-run-check-cell")
        async def check_cell(input: NotebookRunCellCheckInput) -> str:
            recorder.checks.append(input.node_run_id)
            queued = recorder._pending[input.node_run_id]
            return queued.pop(0) if len(queued) > 1 else queued[0]

        @activity.defn(name="notebook-run-finish")
        async def finish(input: NotebookRunFinishInput) -> None:
            recorder.finished.append(input)

        @activity.defn(name="notebook-run-stop-cell")
        async def stop_cell(input: NotebookRunInput) -> None:
            recorder.stopped += 1
            recorder.running.clear()

        return [read_status, advance, dispatch_cell, check_cell, finish, stop_cell]


async def _run_workflow(recorder: _Recorder, node_ids: list[str]) -> None:
    task_queue = str(uuid.uuid4())
    inputs = NotebookRunInput(notebook_run_id=str(uuid.uuid4()), team_id=1, node_ids=node_ids)
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[NotebookRunWorkflow],
            activities=recorder.activities(),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await environment.client.execute_workflow(
                NotebookRunWorkflow.run, inputs, id=str(uuid.uuid4()), task_queue=task_queue
            )


@pytest.mark.asyncio
async def test_every_cell_runs_in_document_order() -> None:
    recorder = _Recorder()

    await _run_workflow(recorder, ["a", "b", "c"])

    assert recorder.dispatched == [0, 1, 2]
    assert [(f.status, f.failed_node_id) for f in recorder.finished] == [(NotebookRun.Status.DONE, None)]
    # Past the last cell, so the status endpoint stops naming cell 3 as the one in flight
    # and the completion event counts all three rather than two.
    assert recorder.advanced == [3]


@pytest.mark.asyncio
async def test_a_failing_cell_stops_the_ones_after_it() -> None:
    recorder = _Recorder(cell_statuses={1: [NotebookNodeRun.Status.FAILED]})

    await _run_workflow(recorder, ["a", "b", "c"])

    assert recorder.dispatched == [0, 1]
    assert [(f.status, f.failed_node_id) for f in recorder.finished] == [(NotebookRun.Status.FAILED, "b")]


@pytest.mark.asyncio
@pytest.mark.parametrize("cell_status", [NotebookNodeRun.Status.RUNNING, NotebookNodeRun.Status.DONE])
async def test_an_interrupt_stops_the_loop_before_the_next_dispatch(cell_status: str) -> None:
    # The endpoint writes the outcome, so the loop must leave the record alone.
    recorder = _Recorder(
        cell_statuses={0: [cell_status]},
        run_statuses=[NotebookRun.Status.RUNNING, NotebookRun.Status.RUNNING, NotebookRun.Status.INTERRUPTED],
    )

    await _run_workflow(recorder, ["a", "b", "c"])

    assert recorder.dispatched == [0]
    assert recorder.checks == ["run-0"]
    assert recorder.finished == []


@pytest.mark.asyncio
async def test_exhausted_dispatch_retries_stop_the_child_that_was_submitted() -> None:
    recorder = _Recorder(fail_dispatch=True)

    await _run_workflow(recorder, ["a", "b"])

    assert recorder.dispatched
    assert set(recorder.dispatched) == {0}
    assert [(f.status, f.failed_node_id) for f in recorder.finished] == [(NotebookRun.Status.FAILED, "a")]
    assert recorder.stopped == 1
    assert recorder.running == set()


@pytest.mark.asyncio
async def test_a_cell_is_polled_until_it_reaches_a_terminal_state() -> None:
    # The direct lane only turns terminal when somebody reads it, so a single check is not
    # an answer.
    recorder = _Recorder(
        cell_statuses={0: [NotebookNodeRun.Status.RUNNING, NotebookNodeRun.Status.RUNNING, NotebookNodeRun.Status.DONE]}
    )

    await _run_workflow(recorder, ["a"])

    assert recorder.checks == ["run-0", "run-0", "run-0"]
    assert [f.status for f in recorder.finished] == [NotebookRun.Status.DONE]
