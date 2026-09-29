"""The browser kernel's two touchpoints with the backend: planning a cell run, and recording it.

A notebook set to the browser kernel runs Python and DuckDB cells in the user's own tab with
Pyodide, so no sandbox is involved. The backend still owns what a cell means, though: which
upstream run a name resolves to, how notebook variables bind, and whether SQL pushes to
ClickHouse at all. `plan_browser_run` answers that with the same resolution a sandbox run gets,
without dispatching anything. `record_browser_run` then files the finished run like any other,
so widget generation, cross-cell references, reloads and the agent state view all see it.
"""

from typing import Any, Literal

from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS

from posthog.dataclasses import frozen
from posthog.models import User

from products.notebooks.backend.models import NotebookNodeRun
from products.notebooks.backend.sql_v2_direct import apply_page_bounds
from products.notebooks.backend.sql_v2_dispatch import (
    NodeRunRequest,
    resolve_node_run_plan,
    resolve_team_notebook,
    resolve_user,
)
from products.notebooks.backend.sql_v2_variables import python_variable_bindings

# Stored on the envelope so a reader can tell a result that only ever existed in someone's tab
# from a sandbox result it could page through.
BROWSER_EXECUTOR = "browser"

# Inputs travel through the query API as JSON and land in the tab's memory, so they use the
# API's own row ceiling rather than the sandbox's much larger one.
BROWSER_INPUT_ROW_LIMIT = MAX_SELECT_RETURNED_ROWS

_STATUS_BY_OUTCOME = {
    "ok": NotebookNodeRun.Status.DONE,
    "interrupted": NotebookNodeRun.Status.INTERRUPTED,
}


@frozen
class BrowserRunInput:
    name: str
    kind: Literal["hogql", "local"]
    node_id: str | None = None
    key: str | None = None
    # HogQL that returns the upstream rows, bounded to BROWSER_INPUT_ROW_LIMIT.
    query: str | None = None


@frozen
class BrowserRunPlan:
    node_type: Literal["hogql", "duckdb", "python"]
    code: str
    inputs: list[BrowserRunInput]
    # Python: globals to bind. DuckDB: `$name` parameters for the driver. HogQL: always empty.
    variables: dict[str, Any]


def plan_browser_run(*, team_id: int, notebook_short_id: str, request: NodeRunRequest) -> BrowserRunPlan:
    """Resolve a cell run the way dispatch would, without starting one.

    Raises `NodeRunInvalid` for a run the user has to fix, with the same message dispatch gives.
    """
    notebook = resolve_team_notebook(team_id, notebook_short_id)
    plan = resolve_node_run_plan(notebook, request)
    inputs: list[BrowserRunInput] = []
    for spec in plan.inputs:
        if spec["kind"] == "local":
            inputs.append(BrowserRunInput(name=spec["name"], kind="local"))
            continue
        inputs.append(
            BrowserRunInput(
                name=spec["name"],
                kind="hogql",
                node_id=spec["node_id"],
                key=str(spec["run_id"]),
                query=apply_page_bounds(spec["query"], limit=BROWSER_INPUT_ROW_LIMIT, offset=0),
            )
        )
    variables: dict[str, Any] = (
        python_variable_bindings(request.variables) if plan.node_type == "python" else dict(plan.variables)
    )
    return BrowserRunPlan(node_type=plan.node_type, code=plan.code, inputs=inputs, variables=variables)


def record_browser_run(
    *,
    team_id: int,
    notebook_short_id: str,
    user_id: int | None,
    node_id: str,
    node_type: Literal["python", "duckdb"],
    code: str,
    envelope: dict[str, Any],
) -> NotebookNodeRun:
    """File a run the browser kernel finished, as a terminal run row."""
    notebook = resolve_team_notebook(team_id, notebook_short_id)
    user: User | None = resolve_user(user_id)
    status = _STATUS_BY_OUTCOME.get(str(envelope.get("status")), NotebookNodeRun.Status.FAILED)
    # The frame catalog describes one tab's kernel, which no other reader can query.
    stored = {key: value for key, value in envelope.items() if key not in ("frames", "result_id")}
    stored["executor"] = BROWSER_EXECUTOR
    error = envelope.get("error") or None
    if status == NotebookNodeRun.Status.FAILED and not error:
        error = "Run failed"
    return NotebookNodeRun.objects.for_team(team_id).create(
        team_id=team_id,
        notebook=notebook,
        user=user,
        node_id=node_id,
        node_type=node_type,
        code=code,
        status=status,
        envelope=stored,
        error=error if status != NotebookNodeRun.Status.DONE else None,
    )


def is_browser_run(run: NotebookNodeRun) -> bool:
    return isinstance(run.envelope, dict) and run.envelope.get("executor") == BROWSER_EXECUTOR


__all__ = [
    "BROWSER_INPUT_ROW_LIMIT",
    "BrowserRunInput",
    "BrowserRunPlan",
    "is_browser_run",
    "plan_browser_run",
    "record_browser_run",
]
