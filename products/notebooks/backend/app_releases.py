from datetime import datetime
from uuid import UUID

from django.db.models import QuerySet

from rest_framework.exceptions import ValidationError

from products.notebooks.backend.facade.contracts import AppBlockSource, AppRelease, AppReleaseReview
from products.notebooks.backend.markdown_collab import get_markdown_notebook_markdown
from products.notebooks.backend.models import Notebook, NotebookAppRelease, NotebookNodeRun
from products.notebooks.backend.python_analysis import analyze_python_globals
from products.notebooks.backend.sql_v2_state import (
    MAX_ADDRESSABLE_PROSE_BLOCKS,
    NotebookCellState,
    annotate_run_state,
    build_dependency_edges,
    extract_cells,
)
from products.notebooks.backend.sql_v2_variables import (
    build_notebook_variables,
    python_variable_bindings,
    substitute_duckdb_variables,
)
from products.notebooks.backend.util import _parse_markdown_component_props, iter_markdown_blocks


def releases_for(notebook: Notebook) -> QuerySet[NotebookAppRelease]:
    return NotebookAppRelease.objects.for_team(notebook.team_id).filter(notebook=notebook).order_by("-revision")


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
    restore = releases_for(notebook)[1:2].first() if restore_previous else None
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

    NotebookAppRelease.objects.for_team(notebook.team_id).create(
        notebook=notebook,
        team_id=notebook.team_id,
        revision=notebook.app_revision,
        results_as_of=results_as_of,
        markdown=restore.markdown if restore else markdown,
        variables=restore.variables if restore else notebook.variables or [],
        title=restore.title if restore else notebook.title or "",
        layout=layout,
    )


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
    cells = extract_cells(notebook.content)
    build_dependency_edges(cells)
    annotate_run_state(cells, notebook.team_id, notebook)
    states = {cell.node_id: cell for cell in cells}
    runs = {
        str(run.pk): run
        for run in NotebookNodeRun.objects.for_team(notebook.team_id)
        .filter(notebook=notebook, id__in=[cell.last_run["run_id"] for cell in cells if cell.last_run])
        .only("id", "connection_id", "send_raw_query", "node_type", "notebook_run__variables")
        .select_related("notebook_run")
    }
    stale_ids = {
        cell.node_id
        for cell in cells
        if cell.status != "done"
        or (
            cell.last_run
            and ((run := runs.get(cell.last_run["run_id"])) is None or not inputs_match(cell, run, notebook))
        )
    }
    pending = list(stale_ids)
    while pending:
        for dependent in states[pending.pop()].dependents:
            if dependent not in stale_ids:
                stale_ids.add(dependent)
                pending.append(dependent)
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
        elif block.display != "source" and sources[node_id].tag_name in ("SQLV2", "PythonV2"):
            cell = states.get(node_id)
            if not cell or not cell.last_run or node_id in stale_ids:
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


def inputs_match(cell: NotebookCellState, run: NotebookNodeRun, notebook: Notebook) -> bool:
    if (
        str(run.connection_id) if run.connection_id else None
    ) != cell.connection_id or run.send_raw_query != cell.send_raw_query:
        return False
    if run.node_type not in (NotebookNodeRun.NodeType.PYTHON, NotebookNodeRun.NodeType.DUCKDB):
        return True
    current = build_notebook_variables(notebook.variables or [])
    previous = build_notebook_variables(run.notebook_run.variables if run.notebook_run else [])
    current_values = python_variable_bindings(current)
    previous_values = python_variable_bindings(previous)
    if run.node_type == NotebookNodeRun.NodeType.PYTHON:
        names = set(analyze_python_globals(cell.code).used) & (current_values.keys() | previous_values.keys())
    else:
        names = set(substitute_duckdb_variables(cell.code, current)[1])
    return all(
        name in current_values and name in previous_values and current_values[name] == previous_values[name]
        for name in names
    )
