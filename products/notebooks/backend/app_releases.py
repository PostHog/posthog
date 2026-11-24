from datetime import datetime
from uuid import UUID

from django.db.models import QuerySet

from rest_framework.exceptions import ValidationError

from products.notebooks.backend.app_release_results import capture_published_sql_rows
from products.notebooks.backend.facade.contracts import AppBlockSource, AppRelease, AppReleaseReview
from products.notebooks.backend.markdown_collab import get_markdown_notebook_markdown
from products.notebooks.backend.models import Notebook, NotebookAppRelease, NotebookNodeRun
from products.notebooks.backend.sql_v2_state import (
    MAX_ADDRESSABLE_PROSE_BLOCKS,
    NotebookCellState,
    annotate_run_state,
    build_dependency_edges,
    extract_cells,
)
from products.notebooks.backend.sql_v2_variables import (
    NotebookVariable,
    build_notebook_variables,
    python_variable_bindings,
    substitute_duckdb_variables,
)
from products.notebooks.backend.util import _parse_markdown_component_props, iter_markdown_blocks


def releases_for(notebook: Notebook) -> QuerySet[NotebookAppRelease]:
    return (
        NotebookAppRelease.objects.for_team(notebook.team_id)
        .filter(notebook=notebook)
        .defer("sql_rows")
        .order_by("-revision")
    )


def read_release(team_id: int, notebook_id: UUID, *, previous: bool = False) -> AppRelease | None:
    notebook = Notebook.objects.get(team_id=team_id, pk=notebook_id)
    if notebook.deleted or notebook.app_published is None:
        return None
    releases = releases_for(notebook)
    current = releases[1:2].first() if previous else releases.first()
    if previous and current is None:
        return None
    return AppRelease(
        revision=current.revision if current else notebook.app_revision,
        published_at=current.published_at if current else None,
        results_as_of=current.results_as_of if current else None,
        title=current.title if current else notebook.title or "",
        layout=current.layout if current else notebook.app_published,
        markdown=current.markdown if current else get_markdown_notebook_markdown(notebook.content) or "",
        variables=current.variables if current else notebook.variables or [],
        has_previous=current is not None and releases.filter(revision__lt=current.revision).exists(),
    )


def record_release(team_id: int, notebook_id: UUID, *, restore_previous: bool = False) -> None:
    notebook = Notebook.objects.get(team_id=team_id, pk=notebook_id)
    releases = releases_for(notebook)
    restore = releases[1:2].first() if restore_previous else None
    markdown = get_markdown_notebook_markdown(notebook.content) or ""
    layout = notebook.app_published
    if not layout:
        raise ValidationError("Choose an app layout to publish.")

    if restore:
        results_as_of = restore.results_as_of
    else:
        review = review_sources(notebook, markdown, [AppBlockSource(**block) for block in layout["blocks"]])
        if review.problems:
            raise ValidationError({"app_published": review.problems})
        results_as_of = review.results_as_of

    releases.create(
        notebook=notebook,
        team_id=notebook.team_id,
        revision=notebook.app_revision,
        results_as_of=results_as_of,
        markdown=restore.markdown if restore else markdown,
        variables=restore.variables if restore else notebook.variables or [],
        title=restore.title if restore else notebook.title or "",
        layout=layout,
        sql_rows=restore.sql_rows if restore else capture_published_sql_rows(notebook, markdown, layout),
    )
    releases.exclude(pk__in=releases.values("pk")[:2]).delete()


def review_release(team_id: int, notebook_id: UUID, blocks: list[AppBlockSource]) -> AppReleaseReview:
    notebook = Notebook.objects.get(team_id=team_id, pk=notebook_id)
    return review_sources(notebook, get_markdown_notebook_markdown(notebook.content) or "", blocks)


def review_sources(notebook: Notebook, markdown: str, blocks: list[AppBlockSource]) -> AppReleaseReview:
    sources = {
        block.node_id: block
        for block in iter_markdown_blocks(
            markdown, max_prose_blocks=MAX_ADDRESSABLE_PROSE_BLOCKS, group_anchored_prose=True
        )
    }
    variables = {variable["name"] for variable in notebook.variables or []}
    result_ids = {
        block.node_id
        for block in blocks
        if block.kind == "cell"
        and block.display != "source"
        and block.node_id in sources
        and sources[block.node_id].tag_name in ("SQLV2", "PythonV2")
    }
    states = release_cell_states(notebook, result_ids)
    problems: list[str] = []
    completed: list[datetime] = []
    for block in blocks:
        name = block.title or block.id
        if block.kind == "input" and block.variable not in variables:
            problems.append(f"{name}: choose an existing notebook variable.")
        if block.kind != "cell":
            continue
        node_id = block.node_id
        if node_id not in sources:
            problems.append(f"{name}: the source cell is missing.")
        elif block.display != "source" and node_id in result_ids:
            cell = states.get(node_id)
            if not cell or not cell.last_run or cell.status != "done":
                status = cell.status if cell and cell.status != "done" else "stale"
                problems.append(f"{name}: run the notebook to refresh this result ({status}).")
                continue
            props = _parse_markdown_component_props(sources[node_id].source)
            if props.get("runId") != cell.last_run["run_id"] or not isinstance(props.get("result"), dict):
                problems.append(f"{name}: run the preview and wait for the result to save.")
                continue
            completed.append(cell.last_run["finished_at"])
    return AppReleaseReview(
        problems=problems,
        results_as_of=min(completed, default=None),
        has_previous=notebook.app_published is not None and releases_for(notebook)[1:2].exists(),
    )


def release_cell_states(notebook: Notebook, result_ids: set[str]) -> dict[str, NotebookCellState]:
    if not result_ids:
        return {}
    cells = extract_cells(notebook.content)
    build_dependency_edges(cells)
    states = {cell.node_id: cell for cell in cells}
    required: dict[str, NotebookCellState] = {}
    pending = list(result_ids.intersection(states))
    while pending:
        node_id = pending.pop()
        if node_id not in required:
            required[node_id] = states[node_id]
            pending.extend(states[node_id].depends_on)
    runs = annotate_run_state(list(required.values()), notebook.team_id, notebook, for_release=True)
    variables = build_notebook_variables(notebook.variables or [])
    for cell in required.values():
        if cell.status == "done" and not inputs_match(cell, runs[cell.node_id], variables):
            cell.status = "stale"
    pending = [node_id for node_id, cell in required.items() if cell.status != "done"]
    while pending:
        for dependent in required[pending.pop()].dependents:
            if dependent in required and required[dependent].status == "done":
                required[dependent].status = "stale"
                pending.append(dependent)
    return required


def inputs_match(cell: NotebookCellState, run: NotebookNodeRun, current: list[NotebookVariable]) -> bool:
    if (
        str(run.connection_id) if run.connection_id else None
    ) != cell.connection_id or run.send_raw_query != cell.send_raw_query:
        return False
    if run.node_type not in (NotebookNodeRun.NodeType.PYTHON, NotebookNodeRun.NodeType.DUCKDB):
        return True
    python = run.node_type == NotebookNodeRun.NodeType.PYTHON
    # Python can read any bound name dynamically, including names that shadow builtins.
    expected = python_variable_bindings(current) if python else substitute_duckdb_variables(cell.code, current)[1]
    previous = run.bound_variables
    if previous is None:
        if run.notebook_run is None:
            return not python and not expected
        old_namespace = python_variable_bindings(build_notebook_variables(run.notebook_run.variables))
        previous = old_namespace if python else {key: old_namespace[key] for key in expected if key in old_namespace}
    return expected.keys() == previous.keys() and all(
        type(value) is type(previous[name]) and value == previous[name] for name, value in expected.items()
    )
