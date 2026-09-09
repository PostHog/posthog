"""Temporal workflow/activities that walk a whole-notebook run.

The run endpoint starts this fire-and-forget. The workflow dispatches one cell, polls it
to a terminal state, and moves to the next, stopping at the first cell that fails or is
interrupted. Polling is what the direct (pure HogQL) lane needs: that lane only advances
when somebody reads the run, and in a headless run nobody does.

Each poll is a short activity with a Temporal timer between them, so a long cell holds a
timer rather than a worker slot.
"""

from datetime import datetime, timedelta

import structlog
from temporalio import activity, common, workflow

from posthog.models.user import User
from posthog.temporal.common.base import PostHogWorkflow

from products.notebooks.backend.models import Notebook, NotebookNodeRun, NotebookRun
from products.notebooks.backend.sql_v2_direct import sync_direct_run
from products.notebooks.backend.sql_v2_runs import expire_stale_kernel_run
from products.notebooks.backend.temporal.notebook_run_inputs import (
    NOTEBOOK_RUN_BUDGET_SECONDS,
    CellDispatched,
    CellRunLookup,
    CellStatus,
    NotebookRunCellInput,
    NotebookRunFinish,
    NotebookRunInput,
)

# How long the workflow waits between two status reads of the cell in flight. Short at
# first so a fast SQL cell does not sit finished for seconds, then longer, because a cell
# that is still working after half a minute is usually working for minutes and every poll
# costs two history events.
_FAST_POLL_SECONDS = 2
_SLOW_POLL_SECONDS = 5
_FAST_POLL_COUNT = 15

_RUN_TIMEOUT_ERROR = "The run took longer than an hour, so it was stopped."

# How long a single dispatch may keep retrying a busy notebook. Somebody running one cell
# by hand holds the notebook's slot for as long as that cell runs, and the run should wait
# for it rather than give up on the first refusal.
_DISPATCH_RETRY_BUDGET = timedelta(minutes=2)

logger = structlog.get_logger(__name__)


def _load_run(team_id: int, notebook_run_id: str) -> NotebookRun | None:
    return NotebookRun.objects.for_team(team_id).select_related("notebook").filter(id=notebook_run_id).first()


@activity.defn(name="notebook-run-dispatch-cell")
def dispatch_notebook_run_cell_activity(input: NotebookRunCellInput) -> CellDispatched:
    # Deferred: the workflow registry in temporal/__init__.py imports this module, and the
    # dispatch code below reaches back into temporal/client.py to start a cell's own
    # workflow. Importing either at module level closes that loop.
    from products.notebooks.backend.notebook_runs import (  # noqa: PLC0415 — breaks the temporal registry -> dispatch import cycle
        advance_notebook_run,
        build_cell_run_request,
        read_cell_plan,
    )
    from products.notebooks.backend.sql_v2_dispatch import (  # noqa: PLC0415 — breaks the temporal registry -> dispatch import cycle
        NodeRunDispatchFailed,
        NodeRunInvalid,
        dispatch_node_run,
    )

    notebook_run = _load_run(input.team_id, input.notebook_run_id)
    if notebook_run is None:
        return CellDispatched(outcome="failed", error="The run no longer exists.")
    # The interrupt endpoint marks the row; this read is where that reaches the loop.
    if notebook_run.status != NotebookRun.Status.RUNNING:
        return CellDispatched(outcome="interrupted")

    cells = read_cell_plan(notebook_run)
    if input.index >= len(cells):
        return CellDispatched(outcome="finished")
    advance_notebook_run(notebook_run, input.index)

    # Re-read the document: a cell edited since the run started runs what the editor shows.
    notebook = Notebook.objects.get(pk=notebook_run.notebook_id)
    # By id rather than through the FK: it is db_constraint=False, so a hard-deleted user
    # leaves an id that raises on descriptor access instead of reading back as None.
    user = User.objects.filter(id=notebook_run.user_id).first() if notebook_run.user_id else None
    request = build_cell_run_request(notebook, notebook_run, cells, input.index)
    if not request.code.strip():
        # The cell lost its code between the plan and its turn. Skipping keeps the run going;
        # failing here would stop a run over an edit the person made on purpose.
        return CellDispatched(outcome="dispatched", node_id=cells[input.index].node_id)

    log = logger.bind(
        notebook_short_id=notebook.short_id,
        notebook_run_id=input.notebook_run_id,
        index=input.index,
        node_id=cells[input.index].node_id,
    )
    try:
        dispatch = dispatch_node_run(notebook, user, notebook.team, request)
    except (NodeRunInvalid, NodeRunDispatchFailed) as e:
        # The cell cannot run at all — a bad reference, a parse error, no lane would take
        # it. Retrying would not change the answer, so stop the run on it.
        log.warning("notebook_run_cell_rejected")
        return CellDispatched(outcome="failed", node_id=cells[input.index].node_id, error=str(e))
    log.info("notebook_run_cell_dispatched", node_run_id=str(dispatch.run_id))
    return CellDispatched(outcome="dispatched", node_run_id=str(dispatch.run_id), node_id=cells[input.index].node_id)


@activity.defn(name="notebook-run-check-cell")
def check_notebook_run_cell_activity(input: CellRunLookup) -> CellStatus:
    run = NotebookNodeRun.objects.for_team(input.team_id).filter(id=input.node_run_id).first()
    if run is None:
        return CellStatus(status=NotebookNodeRun.Status.FAILED, error="The cell run no longer exists.")
    # The two lanes' watchdogs, both no-ops for the other lane. `sync_direct_run` is the
    # only thing that advances a pure-HogQL run, and in a headless run this is its only
    # reader; `expire_stale_kernel_run` catches a sandbox callback that never arrived.
    sync_direct_run(run)
    expire_stale_kernel_run(run)
    return CellStatus(status=run.status, error=run.error)


@activity.defn(name="notebook-run-finish")
def finish_notebook_run_activity(input: NotebookRunFinish) -> None:
    from products.notebooks.backend.notebook_runs import (  # noqa: PLC0415 — breaks the temporal registry -> dispatch import cycle
        finish_notebook_run,
    )

    notebook_run = _load_run(input.team_id, input.notebook_run_id)
    if notebook_run is None:
        return
    finish_notebook_run(
        notebook_run,
        NotebookRun.Status(input.status),
        failed_node_id=input.failed_node_id,
        error=input.error,
    )
    logger.info(
        "notebook_run_finished",
        notebook_short_id=notebook_run.notebook.short_id,
        notebook_run_id=input.notebook_run_id,
        index=notebook_run.current_index,
        node_id=input.failed_node_id,
        status=notebook_run.status,
    )


def _poll_delay(poll_index: int) -> timedelta:
    return timedelta(seconds=_FAST_POLL_SECONDS if poll_index < _FAST_POLL_COUNT else _SLOW_POLL_SECONDS)


@workflow.defn(name="notebook-run")
class NotebookRunWorkflow(PostHogWorkflow):
    inputs_cls = NotebookRunInput

    @workflow.run
    async def run(self, input: NotebookRunInput) -> None:
        deadline = workflow.now() + timedelta(seconds=NOTEBOOK_RUN_BUDGET_SECONDS)
        index = 0
        while True:
            if workflow.now() >= deadline:
                await self._finish(input, NotebookRun.Status.FAILED, error=_RUN_TIMEOUT_ERROR)
                return

            dispatched = await workflow.execute_activity(
                dispatch_notebook_run_cell_activity,
                NotebookRunCellInput(notebook_run_id=input.notebook_run_id, team_id=input.team_id, index=index),
                start_to_close_timeout=timedelta(seconds=60),
                # A busy notebook and a full team ceiling both raise out of the activity, and
                # both clear on their own, so retry inside this budget before giving up.
                schedule_to_close_timeout=_DISPATCH_RETRY_BUDGET,
                retry_policy=common.RetryPolicy(
                    maximum_attempts=0,
                    initial_interval=timedelta(seconds=2),
                    maximum_interval=timedelta(seconds=15),
                ),
            )
            if dispatched.outcome == "finished":
                await self._finish(input, NotebookRun.Status.DONE)
                return
            if dispatched.outcome == "interrupted":
                return
            if dispatched.outcome == "failed":
                await self._finish(
                    input,
                    NotebookRun.Status.FAILED,
                    failed_node_id=dispatched.node_id,
                    error=dispatched.error,
                )
                return

            if dispatched.node_run_id is not None:
                status = await self._await_cell(
                    CellRunLookup(node_run_id=dispatched.node_run_id, team_id=input.team_id), deadline
                )
                if status.status == NotebookNodeRun.Status.RUNNING:
                    await self._finish(
                        input,
                        NotebookRun.Status.FAILED,
                        failed_node_id=dispatched.node_id,
                        error=_RUN_TIMEOUT_ERROR,
                    )
                    return
                if status.status != NotebookNodeRun.Status.DONE:
                    await self._finish(
                        input,
                        (
                            NotebookRun.Status.INTERRUPTED
                            if status.status == NotebookNodeRun.Status.INTERRUPTED
                            else NotebookRun.Status.FAILED
                        ),
                        failed_node_id=dispatched.node_id,
                        error=status.error,
                    )
                    return
            index += 1

    async def _await_cell(self, lookup: CellRunLookup, deadline: datetime) -> CellStatus:
        poll_index = 0
        while True:
            status = await workflow.execute_activity(
                check_notebook_run_cell_activity,
                lookup,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1)),
            )
            if status.status != NotebookNodeRun.Status.RUNNING:
                return status
            if workflow.now() >= deadline:
                return status
            await workflow.sleep(_poll_delay(poll_index))
            poll_index += 1

    async def _finish(
        self,
        input: NotebookRunInput,
        status: NotebookRun.Status,
        *,
        failed_node_id: str | None = None,
        error: str | None = None,
    ) -> None:
        await workflow.execute_activity(
            finish_notebook_run_activity,
            NotebookRunFinish(
                notebook_run_id=input.notebook_run_id,
                team_id=input.team_id,
                status=str(status),
                failed_node_id=failed_node_id,
                error=error,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            # Idempotent (status-guarded), so retry until it lands rather than leaving the
            # row RUNNING with nothing left to move it.
            schedule_to_close_timeout=timedelta(minutes=30),
            retry_policy=common.RetryPolicy(maximum_attempts=0),
        )
