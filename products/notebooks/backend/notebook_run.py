"""Drive every runnable cell of one markdown notebook, in document order.

The orchestration lives in the backend, so the editor and an agent over MCP start the same
run through the same endpoints. This module owns the run record: planning the cells,
starting the workflow, reading the run back, stopping it, and closing it out. The Temporal
workflow in `temporal/notebook_run.py` is the loop that walks the plan, and it calls the
same `dispatch_node_run` a person's click does.

Document order is dependency order: a cell can only read exports of earlier cells, which is
the rule the editor's staleness chain already relies on. So the plan needs no sorting.
"""

from typing import Any
from uuid import UUID

from django.db import IntegrityError
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.notebooks.backend.models import Notebook, NotebookNodeRun, NotebookRun
from products.notebooks.backend.sql_v2 import SQLV2KernelNotRunning, interrupt_sql_v2_run
from products.notebooks.backend.sql_v2_direct import cancel_direct_run
from products.notebooks.backend.sql_v2_dispatch import NodeRunRequest, RefSpec, sandbox_disclosure
from products.notebooks.backend.sql_v2_metrics import (
    OUTCOME_TIMED_OUT,
    outcome_for_status,
    record_notebook_run_terminal,
)
from products.notebooks.backend.sql_v2_runs import finish_node_run
from products.notebooks.backend.sql_v2_state import extract_cells
from products.notebooks.backend.sql_v2_variables import build_notebook_variables

logger = structlog.get_logger(__name__)

# The cell kinds a run executes. A `Query` cell embeds a saved insight and a widget renders
# a frame, so neither has code to run.
RUNNABLE_CELL_TYPES = ("sql", "python")

_NOTHING_TO_RUN = (
    "This notebook has no SQL or Python cells with code in them, so there is nothing to run. Add a cell first."
)
_ALREADY_RUNNING = "This notebook is already running. Wait for it to finish, or stop it first."


class NotebookRunNothingToRun(Exception):
    """The notebook holds no cell this run could execute."""


class NotebookRunAlreadyRunning(Exception):
    """A whole-notebook run is already in flight for this notebook."""


@frozen
class NotebookRunStart:
    """What the caller has to tell the user once a whole-notebook run is on its way."""

    notebook_run: NotebookRun
    cell_count: int
    starts_sandbox: bool
    sandbox_hourly_price: float | None


def plan_notebook_cells(notebook: Notebook) -> list[dict[str, str]]:
    """The cells this run will execute, in document order, as the plan is stored.

    Frozen at start: a cell added while the run works does not join it, and a cell deleted
    while it works still runs, because the plan no longer reads the document.
    """
    return [
        {"node_id": cell.node_id, "cell_type": cell.cell_type, "dataframe_name": cell.dataframe_name}
        for cell in extract_cells(notebook.content)
        if cell.cell_type in RUNNABLE_CELL_TYPES and cell.code.strip()
    ]


def start_notebook_run(
    notebook: Notebook,
    user: User | None,
    team: Team,
    *,
    trigger: str,
) -> NotebookRunStart:
    """Create the run record for `notebook` and price the sandbox it may start.

    The caller saves any new variables before calling this, so the snapshot the run binds
    matches the document a reader will compare the results against. Starting the workflow is
    the caller's last step, once the record exists.
    """
    cell_plan = plan_notebook_cells(notebook)
    if not cell_plan:
        raise NotebookRunNothingToRun(_NOTHING_TO_RUN)

    try:
        notebook_run = NotebookRun.objects.create(
            team_id=team.id,
            notebook=notebook,
            user=user,
            trigger=trigger,
            variables=notebook.variables or [],
            cell_plan=cell_plan,
        )
    except IntegrityError as e:
        # The partial unique constraint, not a lock: one running row per notebook.
        raise NotebookRunAlreadyRunning(_ALREADY_RUNNING) from e

    starts_sandbox, hourly_price = sandbox_disclosure(
        notebook,
        user,
        uses_sandbox=any(cell["cell_type"] == "python" for cell in cell_plan),
    )
    return NotebookRunStart(
        notebook_run=notebook_run,
        cell_count=len(cell_plan),
        starts_sandbox=starts_sandbox,
        sandbox_hourly_price=hourly_price,
    )


def node_run_request_for(notebook_run: NotebookRun, index: int) -> NodeRunRequest:
    """Build the dispatch request for the cell at `index` of the frozen plan.

    Refs follow the run-ref convention the clients use: every earlier SQL cell with a valid
    dataframe name is a `hogql` ref, every earlier Python cell is a `local` ref, and SQL wins
    a name collision. `dispatch_node_run` then keeps only the names the code reads.
    """
    plan: list[dict[str, str]] = notebook_run.cell_plan
    cell = plan[index]
    refs: dict[str, RefSpec] = {}
    for earlier in plan[:index]:
        if earlier["cell_type"] == "sql" and earlier["dataframe_name"]:
            refs.setdefault(earlier["dataframe_name"], RefSpec(node_id=earlier["node_id"], kind="hogql"))
    for earlier in plan[:index]:
        if earlier["cell_type"] == "python" and earlier["dataframe_name"]:
            refs.setdefault(earlier["dataframe_name"], RefSpec(node_id=earlier["node_id"], kind="local"))

    code = _cell_code(notebook_run, cell["node_id"])
    return NodeRunRequest(
        node_id=cell["node_id"],
        node_type="python" if cell["cell_type"] == "python" else "hogql",
        code=code,
        output_name=cell["dataframe_name"],
        refs=refs,
        variables=build_notebook_variables(notebook_run.variables or []),
        notebook_run_id=notebook_run.id,
    )


def _cell_code(notebook_run: NotebookRun, node_id: str) -> str:
    """The cell's code as the document holds it now.

    The plan freezes which cells run, not what they contain: a person editing a later cell
    while the run works expects the run to execute what they can see.
    """
    for cell in extract_cells(notebook_run.notebook.content):
        if cell.node_id == node_id:
            return cell.code
    return ""


def notebook_run_status(notebook_run: NotebookRun) -> dict[str, Any]:
    """The whole run as a client reads it: its state, and one line per planned cell.

    Cheap by design. It carries no result envelopes — a client fetches the one cell it wants
    to show from the existing run-result endpoint.
    """
    plan: list[dict[str, str]] = notebook_run.cell_plan or []
    latest_by_node: dict[str, NotebookNodeRun] = {}
    for node_run in (
        NotebookNodeRun.objects.for_team(notebook_run.team_id)
        .filter(notebook_run=notebook_run)
        .order_by("node_id", "-created_at")
    ):
        latest_by_node.setdefault(node_run.node_id, node_run)

    cells = []
    for cell in plan:
        latest = latest_by_node.get(cell["node_id"])
        cells.append(
            {
                "node_id": cell["node_id"],
                "cell_type": cell["cell_type"],
                "dataframe_name": cell["dataframe_name"],
                "run_id": str(latest.id) if latest else None,
                "status": latest.status if latest else None,
                "error": (latest.error or None) if latest else None,
            }
        )
    current = plan[notebook_run.current_index] if notebook_run.current_index < len(plan) else None
    return {
        "run_id": str(notebook_run.id),
        "status": notebook_run.status,
        "trigger": notebook_run.trigger,
        "variables": notebook_run.variables or [],
        "cell_count": len(plan),
        "current_index": notebook_run.current_index,
        "current_node_id": current["node_id"] if current else None,
        "failed_node_id": notebook_run.failed_node_id,
        "error": notebook_run.error,
        "cells": cells,
        "created_at": notebook_run.created_at,
        "finished_at": notebook_run.finished_at,
    }


def finish_notebook_run(
    notebook_run: NotebookRun,
    status: str,
    *,
    failed_node_id: str | None = None,
    error: str | None = None,
    outcome: str | None = None,
) -> bool:
    """Move a RUNNING run to a terminal state; return whether this call won the transition.

    Guarded on the current status, the same pattern as `finish_node_run`, so a retried
    activity and a racing interrupt stay idempotent and report the run's outcome once.
    """
    updated = (
        NotebookRun.objects.for_team(notebook_run.team_id)
        .filter(id=notebook_run.id, status=NotebookRun.Status.RUNNING)
        .update(
            status=status,
            failed_node_id=failed_node_id,
            error=error,
            finished_at=timezone.now(),
            updated_at=timezone.now(),
        )
    )
    notebook_run.refresh_from_db(
        from_queryset=NotebookRun.objects.for_team(notebook_run.team_id).select_related("user", "notebook")
    )
    if updated:
        record_notebook_run_terminal(notebook_run, outcome or outcome_for_status(status))
    return bool(updated)


def interrupt_notebook_run(notebook: Notebook, user: User | None, notebook_run: NotebookRun) -> bool:
    """Stop a running notebook run; return whether this call stopped it.

    Marks the run first, so the workflow reads `interrupted` before it dispatches the next
    cell even if stopping the current one is slow. Idempotent: interrupting a run that
    already finished changes nothing.
    """
    if not finish_notebook_run(notebook_run, NotebookRun.Status.INTERRUPTED, error="Run stopped."):
        return False
    stop_current_cell(notebook, user, notebook_run)
    return True


def stop_current_cell(notebook: Notebook, user: User | None, notebook_run: NotebookRun) -> None:
    """Stop the cell this run left in flight, whichever lane it is on."""
    run = (
        NotebookNodeRun.objects.for_team(notebook_run.team_id)
        .filter(notebook_run=notebook_run, status=NotebookNodeRun.Status.RUNNING)
        .order_by("-created_at")
        .first()
    )
    if run is None:
        return
    if run.node_type == NotebookNodeRun.NodeType.HOGQL:
        # A direct run has no kernel to signal, so stop it at the query manager. Mark the row
        # first, so the stop is durable even if the cancellation below is slow or fails.
        if finish_node_run(run, NotebookNodeRun.Status.INTERRUPTED, error="Run stopped."):
            cancel_direct_run(run)
        return
    try:
        interrupt_sql_v2_run(notebook, user, run)
    except SQLV2KernelNotRunning:
        # No reachable kernel, so the callback can never arrive. A late one simply overwrites
        # this with the real outcome.
        finish_node_run(
            run, NotebookNodeRun.Status.INTERRUPTED, error="Kernel is not reachable, so the run was stopped."
        )
    except Exception:
        logger.exception("notebook_run_interrupt_cell_failed", notebook_run_id=str(notebook_run.id))


def get_notebook_run(team_id: int, notebook: Notebook, run_id: str | UUID) -> NotebookRun | None:
    return NotebookRun.objects.for_team(team_id).filter(id=run_id, notebook=notebook).first()


def active_notebook_run(team_id: int, notebook: Notebook) -> NotebookRun | None:
    return (
        NotebookRun.objects.for_team(team_id)
        .filter(notebook=notebook, status=NotebookRun.Status.RUNNING)
        .order_by("-created_at")
        .first()
    )


__all__ = [
    "OUTCOME_TIMED_OUT",
    "NotebookRunAlreadyRunning",
    "NotebookRunNothingToRun",
    "NotebookRunStart",
    "active_notebook_run",
    "finish_notebook_run",
    "get_notebook_run",
    "interrupt_notebook_run",
    "node_run_request_for",
    "notebook_run_status",
    "plan_notebook_cells",
    "start_notebook_run",
    "stop_current_cell",
]
