"""Drive every runnable cell of a markdown notebook as one run.

The endpoints and the Temporal workflow both come through here: the endpoint starts a run
and reads its state, the workflow walks the plan. Nothing in this module edits the
document — the clients write each cell's result back themselves, as they do for a single
cell run.

Cells run in document order, which is also dependency order: a cell may only read what an
earlier cell exports. The run stops at the first cell that fails or is interrupted.
"""

from typing import Any, Literal
from uuid import UUID

from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.notebooks.backend.facade.contracts import NotebookRunBusy
from products.notebooks.backend.models import Notebook, NotebookNodeRun, NotebookRun
from products.notebooks.backend.sql_v2 import SQLV2KernelNotRunning, interrupt_sql_v2_run
from products.notebooks.backend.sql_v2_direct import cancel_direct_run
from products.notebooks.backend.sql_v2_dispatch import NodeRunRequest, RefSpec, resolve_sandbox_disclosure
from products.notebooks.backend.sql_v2_metrics import record_notebook_run_terminal
from products.notebooks.backend.sql_v2_runs import finish_node_run
from products.notebooks.backend.sql_v2_state import extract_cells
from products.notebooks.backend.sql_v2_variables import build_notebook_variables

logger = structlog.get_logger(__name__)

# Which cell types a whole-notebook run executes. A Query cell, a widget, and every legacy
# node are documents rather than code, so they are not part of the plan.
RUNNABLE_CELL_TYPES = ("sql", "python")

NO_RUNNABLE_CELLS_ERROR = "This notebook has no SQL or Python cells with code in them, so there is nothing to run."
NOTEBOOK_RUN_BUSY_ERROR = "This notebook is already running. Wait for it to finish, or stop it first."


class NotebookRunHasNoCells(Exception):
    """The notebook holds no cell this run could execute."""


@frozen
class NotebookRunCell:
    node_id: str
    cell_type: Literal["sql", "python"]
    dataframe_name: str = ""

    def as_plan_entry(self) -> dict[str, str]:
        return {"node_id": self.node_id, "cell_type": self.cell_type, "dataframe_name": self.dataframe_name}


@frozen
class NotebookRunStart:
    run_id: UUID
    cell_count: int
    starts_sandbox: bool
    sandbox_hourly_price: float | None


def plan_run_cells(notebook: Notebook) -> list[NotebookRunCell]:
    """The cells this notebook would run, in document order."""
    return [
        NotebookRunCell(
            node_id=cell.node_id,
            cell_type="python" if cell.cell_type == "python" else "sql",
            dataframe_name=cell.dataframe_name,
        )
        for cell in extract_cells(notebook.content)
        if cell.cell_type in RUNNABLE_CELL_TYPES and cell.code.strip()
    ]


def read_cell_plan(notebook_run: NotebookRun) -> list[NotebookRunCell]:
    """The frozen plan, back as dataclasses. A malformed entry is skipped rather than fatal."""
    cells: list[NotebookRunCell] = []
    for entry in notebook_run.cell_plan or []:
        node_id = entry.get("node_id") if isinstance(entry, dict) else None
        if not isinstance(node_id, str) or not node_id:
            continue
        cells.append(
            NotebookRunCell(
                node_id=node_id,
                cell_type="python" if entry.get("cell_type") == "python" else "sql",
                dataframe_name=entry.get("dataframe_name") or "",
            )
        )
    return cells


def refs_for_cell(cells: list[NotebookRunCell], index: int) -> dict[str, RefSpec]:
    """The names the cell at `index` may read, resolved the way the editor resolves them.

    Every earlier SQL cell with a valid dataframe name exports a `hogql` ref, every earlier
    Python cell a `local` one, and a SQL cell wins a name collision. `dispatch_node_run`
    then narrows this to the names the code actually reads.
    """
    earlier = cells[:index]
    refs: dict[str, RefSpec] = {}
    for cell in earlier:
        if cell.cell_type == "sql" and cell.dataframe_name.isidentifier():
            refs.setdefault(cell.dataframe_name, RefSpec(node_id=cell.node_id, kind="hogql"))
    for cell in earlier:
        if cell.cell_type == "python" and cell.dataframe_name.isidentifier():
            refs.setdefault(cell.dataframe_name, RefSpec(node_id=cell.node_id, kind="local"))
    return refs


def build_cell_run_request(
    notebook: Notebook,
    notebook_run: NotebookRun,
    cells: list[NotebookRunCell],
    index: int,
) -> NodeRunRequest:
    """The dispatch request for one planned cell, read from the document as it stands now.

    The plan fixes which cells run; the code comes from the live document, so a cell edited
    between the start and its turn runs what the editor shows.
    """
    cell = cells[index]
    source_by_node = {source.node_id: source for source in extract_cells(notebook.content)}
    source = source_by_node.get(cell.node_id)
    return NodeRunRequest(
        node_id=cell.node_id,
        node_type="python" if cell.cell_type == "python" else "hogql",
        code=source.code if source is not None else "",
        output_name=cell.dataframe_name,
        refs=refs_for_cell(cells, index),
        variables=build_notebook_variables(notebook_run.variables or []),
        # A whole-notebook run always targets PostHog: the plan carries no connection, and a
        # cell that needs one is run on its own from the editor.
        connection_id=None,
        notebook_run_id=notebook_run.id,
        # The start response already told the caller whether a sandbox starts. Asking again
        # per cell would add a sandbox status call to every step of the run.
        disclose_sandbox=False,
    )


def start_notebook_run(
    notebook: Notebook,
    user: User | None,
    team: Team,
    trigger: str,
    variables: list[dict[str, Any]] | None,
) -> NotebookRunStart:
    """Open a run over every runnable cell. Raises when the notebook is busy or has no cells."""
    cells = plan_run_cells(notebook)
    if not cells:
        raise NotebookRunHasNoCells(NO_RUNNABLE_CELLS_ERROR)

    if variables is not None:
        notebook.variables = variables
        notebook.save(update_fields=["variables"])

    snapshot = notebook.variables or []
    try:
        notebook_run = NotebookRun.objects.create(
            team=team,
            notebook=notebook,
            user=user,
            trigger=trigger,
            variables=snapshot,
            cell_plan=[cell.as_plan_entry() for cell in cells],
        )
    except Exception as e:
        # The partial unique index is the only thing that decides this, so a second start
        # never depends on reading the first one back first.
        if _is_active_run_conflict(e):
            raise NotebookRunBusy(NOTEBOOK_RUN_BUSY_ERROR) from e
        raise

    starts_sandbox, hourly_price = resolve_sandbox_disclosure(
        notebook, user, any(cell.cell_type == "python" for cell in cells)
    )
    return NotebookRunStart(
        run_id=notebook_run.id,
        cell_count=len(cells),
        starts_sandbox=starts_sandbox,
        sandbox_hourly_price=hourly_price,
    )


def _is_active_run_conflict(error: Exception) -> bool:
    return "notebook_run_one_active_per_notebook" in str(error)


def finish_notebook_run(
    notebook_run: NotebookRun,
    status: NotebookRun.Status,
    *,
    failed_node_id: str | None = None,
    error: str | None = None,
) -> bool:
    """Move a RUNNING run to a terminal state; return whether this call won the transition.

    Guarded on the current status, the same shape as `finish_node_run`, so an interrupt and
    a workflow finishing at the same moment report one outcome between them.
    """
    finished_at = timezone.now()
    updated = (
        NotebookRun.objects.for_team(notebook_run.team_id)
        .filter(id=notebook_run.id, status=NotebookRun.Status.RUNNING)
        .update(status=status, failed_node_id=failed_node_id, error=error, finished_at=finished_at)
    )
    notebook_run.refresh_from_db(from_queryset=NotebookRun.objects.for_team(notebook_run.team_id))
    if updated:
        record_notebook_run_terminal(notebook_run)
    return bool(updated)


def advance_notebook_run(notebook_run: NotebookRun, index: int) -> None:
    """Record which cell of the plan the run reached, for the status endpoint's progress."""
    NotebookRun.objects.for_team(notebook_run.team_id).filter(id=notebook_run.id).update(current_index=index)


def interrupt_notebook_run(notebook_run: NotebookRun, user: User | None) -> bool:
    """Stop a run before its next cell, and stop the cell that is running now.

    The workflow reads the run's status before every dispatch, so marking the row is what
    ends the loop. Returns whether this call was the one that stopped it.
    """
    if not finish_notebook_run(notebook_run, NotebookRun.Status.INTERRUPTED, error="The run was stopped."):
        return False
    _stop_active_cell(notebook_run, user)
    return True


def _stop_active_cell(notebook_run: NotebookRun, user: User | None) -> None:
    """Best effort stop of the cell this run has in flight.

    The whole-run row is already terminal, so the loop ends either way. What is left is the
    one cell still executing, and it is stopped here rather than through the single-cell
    endpoint because that endpoint's answer is an HTTP status a caller acts on, and this
    caller has nobody to tell.
    """
    run = (
        NotebookNodeRun.objects.for_team(notebook_run.team_id)
        .filter(notebook_run_id=notebook_run.id, status=NotebookNodeRun.Status.RUNNING)
        .order_by("-created_at")
        .first()
    )
    if run is None:
        return
    if run.node_type == NotebookNodeRun.NodeType.HOGQL:
        # A direct run has no kernel to signal. Mark the row first so the stop is durable
        # even if the cancellation below is slow, then stop the query.
        if finish_node_run(run, NotebookNodeRun.Status.INTERRUPTED, error="The run was stopped."):
            cancel_direct_run(run)
        return
    try:
        interrupt_sql_v2_run(notebook_run.notebook, user, run)
    except SQLV2KernelNotRunning:
        # No reachable kernel means no callback can ever arrive, so this is the only thing
        # left that can move the row out of RUNNING.
        finish_node_run(
            run, NotebookNodeRun.Status.INTERRUPTED, error="Kernel is not reachable, so the run was stopped."
        )
    except Exception:
        logger.exception("notebook_run_interrupt_cell_failed", notebook_run_id=str(notebook_run.id))


def cell_runs_by_node(notebook_run: NotebookRun) -> dict[str, NotebookNodeRun]:
    """The latest cell run this whole-notebook run produced, per node."""
    runs = (
        NotebookNodeRun.objects.for_team(notebook_run.team_id)
        .filter(notebook_id=notebook_run.notebook_id, notebook_run_id=notebook_run.id)
        .order_by("node_id", "-created_at")
        .distinct("node_id")
    )
    return {run.node_id: run for run in runs}


def build_run_state(notebook_run: NotebookRun) -> dict[str, Any]:
    """The status payload: where the run is, and how each planned cell went.

    Deliberately envelope-free. A client that wants a cell's rows reads them from the
    existing single-run endpoint, so this stays one small query however big the results are.
    """
    cells = read_cell_plan(notebook_run)
    runs = cell_runs_by_node(notebook_run)
    current = cells[notebook_run.current_index] if 0 <= notebook_run.current_index < len(cells) else None
    return {
        "run_id": str(notebook_run.id),
        "status": notebook_run.status,
        "trigger": notebook_run.trigger,
        "variables": notebook_run.variables or [],
        "current_node_id": current.node_id if current is not None else None,
        "current_index": notebook_run.current_index,
        "failed_node_id": notebook_run.failed_node_id,
        "error": notebook_run.error,
        "cells": [
            {
                "node_id": cell.node_id,
                "cell_type": cell.cell_type,
                "dataframe_name": cell.dataframe_name,
                "run_id": str(runs[cell.node_id].id) if cell.node_id in runs else None,
                "status": runs[cell.node_id].status if cell.node_id in runs else None,
                "error": runs[cell.node_id].error if cell.node_id in runs else None,
            }
            for cell in cells
        ],
        "created_at": notebook_run.created_at,
        "finished_at": notebook_run.finished_at,
    }
