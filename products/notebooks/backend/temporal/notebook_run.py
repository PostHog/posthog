"""Temporal workflow/activities that walk a whole notebook, one cell at a time.

The run endpoint starts this fire-and-forget, and the workflow is the only thing that
advances the run: it dispatches the cell at the current index, polls it to a terminal state,
and moves on. It stops at the first cell that does not finish `done`.

Polling is the workflow's job rather than a client's because a headless run has no client.
A direct (pure HogQL) cell only turns terminal when somebody reads it, so a run nobody
watches would sit RUNNING for good. Each poll is a short activity with a Temporal timer
between calls, so no worker slot is held while a cell works.
"""

import asyncio
from datetime import timedelta

from temporalio import activity, common, workflow
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.models.user import User
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import sync_connect

from products.notebooks.backend.facade.contracts import NotebookRunBusy, TeamRunCapacityFull
from products.notebooks.backend.models import NotebookNodeRun, NotebookRun
from products.notebooks.backend.notebook_run import finish_notebook_run, node_run_request_for, stop_current_cell
from products.notebooks.backend.sql_v2_direct import sync_direct_run
from products.notebooks.backend.sql_v2_dispatch import NodeRunDispatchFailed, NodeRunInvalid, dispatch_node_run
from products.notebooks.backend.sql_v2_metrics import OUTCOME_TIMED_OUT
from products.notebooks.backend.sql_v2_runs import expire_stale_kernel_run
from products.notebooks.backend.temporal.client import _start_workflow

# How long the workflow waits between two polls of the cell it is running. Short enough that
# a fast SQL cell adds no visible latency to a ten-cell run, long enough that a slow Python
# cell costs a handful of queries per minute.
CELL_POLL_INTERVAL_SECONDS = 2

# A cell dispatch that meets a busy notebook or a full project retries for this long before
# the run gives up. A person clicking Run on one cell just as the whole-notebook run reaches
# that cell is the case worth waiting out.
DISPATCH_RETRY_BUDGET = timedelta(minutes=2)

# The watchdog for a run that stops making progress. Every cell has its own budget already;
# this bounds the whole run, so a stuck record cannot stay RUNNING and block the notebook.
NOTEBOOK_RUN_TIMEOUT = timedelta(hours=1)

_CELL_STOPPED_ERROR = "A cell did not finish, so the run stopped there."
_RUN_TIMEOUT_ERROR = "The run took longer than an hour, so it stopped."
_DISPATCH_FAILED_ERROR = "The run could not start a cell."
_RETRYABLE_DISPATCH = "NotebookRunDispatchRetryable"
_UNRECOVERABLE = "NotebookRunUnrecoverable"


@frozen
class NotebookRunInput:
    notebook_run_id: str
    team_id: int
    # The plan's node ids, frozen at start. Carrying them means the loop needs no database
    # read to know how many cells are left or which one it is on.
    node_ids: list[str]


@frozen
class NotebookRunCellInput:
    notebook_run_id: str
    team_id: int
    index: int


@frozen
class NotebookRunCellCheckInput:
    node_run_id: str
    team_id: int


@frozen
class NotebookRunFinishInput:
    notebook_run_id: str
    team_id: int
    status: str
    failed_node_id: str | None = None
    error: str | None = None
    outcome: str | None = None


def _load_run(team_id: int, notebook_run_id: str) -> NotebookRun | None:
    return (
        NotebookRun.objects.for_team(team_id)
        .select_related("notebook", "notebook__team", "user")
        .filter(id=notebook_run_id)
        .first()
    )


@activity.defn(name="notebook-run-read-status")
def read_notebook_run_status_activity(input: NotebookRunInput) -> str:
    notebook_run = _load_run(input.team_id, input.notebook_run_id)
    # A missing record can only mean somebody deleted it, which tells the workflow the same
    # thing an interrupt does: stop.
    return notebook_run.status if notebook_run is not None else NotebookRun.Status.INTERRUPTED


@activity.defn(name="notebook-run-dispatch-cell")
def dispatch_notebook_cell_activity(input: NotebookRunCellInput) -> str:
    """Start the cell at `index` and return its node run id."""
    notebook_run = _load_run(input.team_id, input.notebook_run_id)
    if notebook_run is None:
        raise ApplicationError("The run record is gone.", type=_UNRECOVERABLE, non_retryable=True)

    NotebookRun.objects.for_team(input.team_id).filter(id=notebook_run.id).update(current_index=input.index)
    user = notebook_run.user if isinstance(notebook_run.user, User) else None
    try:
        dispatch = dispatch_node_run(
            notebook_run.notebook,
            user,
            notebook_run.notebook.team,
            node_run_request_for(notebook_run, input.index),
        )
    except (NotebookRunBusy, TeamRunCapacityFull) as e:
        # Someone else holds the notebook's slot, or the project is at its ceiling. Both clear
        # on their own, so retry inside the activity's budget rather than failing the run.
        raise ApplicationError(str(e), type=_RETRYABLE_DISPATCH) from e
    except (NodeRunInvalid, NodeRunDispatchFailed) as e:
        raise ApplicationError(str(e), type=_UNRECOVERABLE, non_retryable=True) from e
    return str(dispatch.run_id)


@activity.defn(name="notebook-run-check-cell")
def check_notebook_cell_activity(input: NotebookRunCellCheckInput) -> str:
    """Advance the cell's row if it needs a reader, and report its status."""
    run = NotebookNodeRun.objects.for_team(input.team_id).filter(id=input.node_run_id).first()
    if run is None:
        return NotebookNodeRun.Status.FAILED
    # The direct lane turns terminal only when somebody polls it, and the kernel lane's
    # envelope arrives in one un-retried POST. Each call is a no-op for the other's lane.
    sync_direct_run(run)
    expire_stale_kernel_run(run)
    run.refresh_from_db(fields=["status"])
    return run.status


@activity.defn(name="notebook-run-finish")
def finish_notebook_run_activity(input: NotebookRunFinishInput) -> None:
    notebook_run = _load_run(input.team_id, input.notebook_run_id)
    if notebook_run is not None:
        finish_notebook_run(
            notebook_run,
            input.status,
            failed_node_id=input.failed_node_id,
            error=input.error,
            outcome=input.outcome,
        )


@activity.defn(name="notebook-run-stop-cell")
def stop_notebook_cell_activity(input: NotebookRunInput) -> None:
    """Stop whatever cell the run left in flight once the run itself is terminal."""
    notebook_run = _load_run(input.team_id, input.notebook_run_id)
    if notebook_run is not None:
        user = notebook_run.user if isinstance(notebook_run.user, User) else None
        stop_current_cell(notebook_run.notebook, user, notebook_run)


@workflow.defn(name="notebook-run")
class NotebookRunWorkflow(PostHogWorkflow):
    inputs_cls = NotebookRunInput

    @workflow.run
    async def run(self, input: NotebookRunInput) -> None:
        try:
            async with asyncio.timeout(NOTEBOOK_RUN_TIMEOUT.total_seconds()):
                await self._walk(input)
        except TimeoutError:
            # The watchdog. Write the outcome first, so the record never stays RUNNING, then
            # release the cell that is still holding the notebook's slot.
            await self._finish(input, NotebookRun.Status.FAILED, error=_RUN_TIMEOUT_ERROR, outcome=OUTCOME_TIMED_OUT)
            await self._stop_cell(input)

    async def _walk(self, input: NotebookRunInput) -> None:
        for index, node_id in enumerate(input.node_ids):
            if await self._run_status(input) != NotebookRun.Status.RUNNING:
                # An interrupt landed between cells. The endpoint already wrote the outcome.
                return
            node_run_id = await self._dispatch(input, index, node_id)
            if node_run_id is None:
                return
            if await self._await_cell(input, node_run_id) == NotebookNodeRun.Status.DONE:
                continue
            if await self._run_status(input) != NotebookRun.Status.RUNNING:
                return
            await self._finish(input, NotebookRun.Status.FAILED, failed_node_id=node_id, error=_CELL_STOPPED_ERROR)
            return
        await self._finish(input, NotebookRun.Status.DONE)

    async def _run_status(self, input: NotebookRunInput) -> str:
        return await workflow.execute_activity(
            read_notebook_run_status_activity,
            input,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=common.RetryPolicy(maximum_attempts=3),
        )

    async def _dispatch(self, input: NotebookRunInput, index: int, node_id: str) -> str | None:
        try:
            return await workflow.execute_activity(
                dispatch_notebook_cell_activity,
                NotebookRunCellInput(notebook_run_id=input.notebook_run_id, team_id=input.team_id, index=index),
                start_to_close_timeout=timedelta(minutes=5),
                schedule_to_close_timeout=DISPATCH_RETRY_BUDGET + timedelta(minutes=5),
                retry_policy=common.RetryPolicy(
                    initial_interval=timedelta(seconds=2),
                    maximum_interval=timedelta(seconds=20),
                    maximum_attempts=0,
                ),
            )
        except Exception as e:
            await self._finish(
                input, NotebookRun.Status.FAILED, failed_node_id=node_id, error=_dispatch_error_message(e)
            )
            return None

    async def _await_cell(self, input: NotebookRunInput, node_run_id: str) -> str:
        check = NotebookRunCellCheckInput(node_run_id=node_run_id, team_id=input.team_id)
        while True:
            status = await workflow.execute_activity(
                check_notebook_cell_activity,
                check,
                start_to_close_timeout=timedelta(seconds=60),
                schedule_to_close_timeout=timedelta(minutes=10),
                retry_policy=common.RetryPolicy(maximum_attempts=0),
            )
            if status != NotebookNodeRun.Status.RUNNING:
                return status
            await workflow.sleep(timedelta(seconds=CELL_POLL_INTERVAL_SECONDS))

    async def _stop_cell(self, input: NotebookRunInput) -> None:
        await workflow.execute_activity(
            stop_notebook_cell_activity,
            input,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=common.RetryPolicy(maximum_attempts=3),
        )

    async def _finish(
        self,
        input: NotebookRunInput,
        status: str,
        *,
        failed_node_id: str | None = None,
        error: str | None = None,
        outcome: str | None = None,
    ) -> None:
        # The run's outcome is its last word, so retry until it lands rather than burning a
        # fixed attempt budget on a brief database outage. The activity is status-guarded.
        await workflow.execute_activity(
            finish_notebook_run_activity,
            NotebookRunFinishInput(
                notebook_run_id=input.notebook_run_id,
                team_id=input.team_id,
                status=status,
                failed_node_id=failed_node_id,
                error=error,
                outcome=outcome,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(hours=1),
            retry_policy=common.RetryPolicy(maximum_attempts=0),
        )


def _dispatch_error_message(error: BaseException) -> str:
    """The sentence a user reads when a cell never started."""
    cause: BaseException | None = error
    while cause is not None:
        if isinstance(cause, ApplicationError) and cause.message:
            return cause.message
        cause = cause.__cause__
    return _DISPATCH_FAILED_ERROR


def start_notebook_run_workflow(inputs: NotebookRunInput) -> None:
    """Start the orchestrator for a run record that already exists.

    A duplicate start is a no-op: the record's status is the loop's stop signal, so a second
    workflow would not be a second orchestrator, and Temporal refuses the id anyway.
    """
    try:
        _start_workflow(
            sync_connect(),
            "notebook-run",
            f"notebook-run-{inputs.notebook_run_id}",
            inputs,
            execution_timeout=NOTEBOOK_RUN_TIMEOUT + timedelta(minutes=5),
        )
    except WorkflowAlreadyStartedError:
        pass
