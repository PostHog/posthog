"""Cell-level state for markdown notebooks: the dependency graph an agent (or the UI)
needs to drive cells — which cells exist, what each depends on, and which are stale.

Staleness is derived, not stored: a cell is stale when re-running it now would execute
different code than its last completed run. For SQL cells that comparison uses the
CTE-resolved code (upstream definitions inline into the stored run code, so an upstream
edit changes the resolution); for Python cells it falls back to raw-code drift plus
upstream run recency (python runs materialize inputs by run, but the run row does not
record which input runs were used).
"""

import re
from dataclasses import dataclass, field
from typing import Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from products.notebooks.backend.models import NotebookNodeRun
from products.notebooks.backend.python_analysis import analyze_python_globals
from products.notebooks.backend.sql_v2_references import _TableReferenceCollector, resolve_sql_v2_references
from products.notebooks.backend.util import (
    _get_markdown_notebook_markdown,
    _iter_markdown_component_blocks,
    _parse_markdown_component_props,
)

_CELL_TAGS = {"SQLV2": "sql", "PythonV2": "python", "Query": "saved_insight"}
_DATAFRAME_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CODE_PREVIEW_CHARS = 8_000


@dataclass
class NotebookCellState:
    node_id: str
    cell_type: str
    dataframe_name: str = ""
    code: str = ""
    status: str = "never_run"
    depends_on: list[str] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)
    last_run: dict[str, Any] | None = None


def extract_cells(content: Any) -> list[NotebookCellState]:
    markdown = _get_markdown_notebook_markdown(content)
    if markdown is None:
        return []
    cells: list[NotebookCellState] = []
    for tag_name, raw, _next_line_index in _iter_markdown_component_blocks(markdown):
        cell_type = _CELL_TAGS.get(tag_name)
        if cell_type is None:
            continue
        props = _parse_markdown_component_props(raw)
        node_id = props.get("nodeId")
        if not isinstance(node_id, str) or not node_id:
            continue
        code = props.get("code")
        dataframe_name = props.get("returnVariable")
        cells.append(
            NotebookCellState(
                node_id=node_id,
                cell_type=cell_type,
                dataframe_name=dataframe_name.strip() if isinstance(dataframe_name, str) else "",
                code=code if isinstance(code, str) else "",
            )
        )
    return cells


def _referenced_names(cell: NotebookCellState, candidates: set[str]) -> set[str]:
    if not candidates or not cell.code.strip():
        return set()
    if cell.cell_type == "python":
        return set(analyze_python_globals(cell.code).used) & candidates
    if cell.cell_type == "sql":
        try:
            query = parse_select(cell.code)
            collector = _TableReferenceCollector(candidates)
            collector.visit(query)
            own_ctes = set(query.ctes.keys()) if isinstance(query, ast.SelectQuery) and query.ctes else set()
            return collector.found - own_ctes
        except Exception:
            # Unparseable code (mid-edit, DuckDB syntax): a word-boundary scan keeps the
            # graph usable instead of dropping every edge.
            return {name for name in candidates if re.search(rf"\b{re.escape(name)}\b", cell.code)}
    return set()


def build_dependency_edges(cells: list[NotebookCellState]) -> None:
    """Populate depends_on/dependents in place. Names follow the run-ref convention:
    SQL cells win dataframe-name collisions, unnamed cells export nothing."""
    owner_by_name: dict[str, str] = {}
    for cell in cells:
        if cell.cell_type == "sql" and _DATAFRAME_NAME.match(cell.dataframe_name):
            owner_by_name.setdefault(cell.dataframe_name, cell.node_id)
    for cell in cells:
        if cell.cell_type == "python" and _DATAFRAME_NAME.match(cell.dataframe_name):
            owner_by_name.setdefault(cell.dataframe_name, cell.node_id)

    by_node: dict[str, NotebookCellState] = {cell.node_id: cell for cell in cells}
    for cell in cells:
        candidates = {name for name, owner in owner_by_name.items() if owner != cell.node_id}
        for name in sorted(_referenced_names(cell, candidates)):
            upstream_id = owner_by_name[name]
            cell.depends_on.append(upstream_id)
            by_node[upstream_id].dependents.append(cell.node_id)


def _is_stale(
    cell: NotebookCellState,
    latest_run: NotebookNodeRun,
    cells_by_node: dict[str, NotebookCellState],
    latest_done_by_node: dict[str, NotebookNodeRun],
) -> bool:
    if cell.cell_type == "sql":
        refs: dict[str, str | None] = {}
        for upstream_id in cell.depends_on:
            upstream = cells_by_node[upstream_id]
            upstream_run = latest_done_by_node.get(upstream_id)
            refs[upstream.dataframe_name] = (
                upstream_run.code if upstream_run is not None and upstream.cell_type == "sql" else None
            )
        try:
            return resolve_sql_v2_references(cell.code, refs) != latest_run.code
        except Exception:
            # No resolvable definition for a referenced upstream (never ran, renamed,
            # deleted): whatever produced the last result no longer reflects the
            # document, which is exactly what stale means.
            return True
    if cell.code.strip() != latest_run.code.strip():
        return True
    for upstream_id in cell.depends_on:
        upstream_run = latest_done_by_node.get(upstream_id)
        if upstream_run is not None and upstream_run.created_at > latest_run.created_at:
            return True
    return False


def annotate_run_state(cells: list[NotebookCellState], team_id: int, notebook: Any) -> None:
    runnable_ids = [cell.node_id for cell in cells if cell.cell_type in ("sql", "python")]
    if not runnable_ids:
        return
    latest_by_node: dict[str, NotebookNodeRun] = {}
    latest_done_by_node: dict[str, NotebookNodeRun] = {}
    runs = (
        NotebookNodeRun.objects.for_team(team_id)
        .filter(notebook=notebook, node_id__in=runnable_ids)
        .order_by("node_id", "-created_at")
    )
    for run in runs:
        if run.node_id not in latest_by_node:
            latest_by_node[run.node_id] = run
        if run.status == NotebookNodeRun.Status.DONE and run.node_id not in latest_done_by_node:
            latest_done_by_node[run.node_id] = run

    cells_by_node = {cell.node_id: cell for cell in cells}
    for cell in cells:
        if cell.cell_type not in ("sql", "python"):
            continue
        latest = latest_by_node.get(cell.node_id)
        if latest is None:
            cell.status = "never_run"
            continue
        envelope = latest.envelope if isinstance(latest.envelope, dict) else {}
        cell.last_run = {
            "run_id": str(latest.id),
            "status": latest.status,
            "finished_at": latest.updated_at,
            "row_count": envelope.get("row_count"),
            "columns": envelope.get("columns"),
            "error": latest.error or envelope.get("error") or None,
        }
        if latest.status == NotebookNodeRun.Status.RUNNING:
            cell.status = "running"
        elif latest.status == NotebookNodeRun.Status.DONE and _is_stale(
            cell, latest, cells_by_node, latest_done_by_node
        ):
            cell.status = "stale"
        else:
            cell.status = latest.status


def build_notebook_cell_state(team_id: int, notebook: Any) -> list[NotebookCellState]:
    cells = extract_cells(notebook.content)
    build_dependency_edges(cells)
    annotate_run_state(cells, team_id, notebook)
    for cell in cells:
        if len(cell.code) > _CODE_PREVIEW_CHARS:
            cell.code = cell.code[:_CODE_PREVIEW_CHARS] + "\n… [truncated]"
    return cells
