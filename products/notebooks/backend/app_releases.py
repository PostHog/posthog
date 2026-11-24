from typing import Any
from uuid import UUID

from django.db.models import QuerySet

from rest_framework.exceptions import ValidationError

from products.notebooks.backend.facade.contracts import AppRelease
from products.notebooks.backend.markdown_collab import get_markdown_notebook_markdown
from products.notebooks.backend.models import Notebook, NotebookAppRelease
from products.notebooks.backend.sql_v2_state import (
    MAX_ADDRESSABLE_PROSE_BLOCKS,
    annotate_run_state,
    build_dependency_edges,
    extract_cells,
)
from products.notebooks.backend.util import iter_markdown_blocks


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

    if not restore:
        validate_release_sources(notebook, markdown, layout)

    NotebookAppRelease.objects.for_team(notebook.team_id).create(
        notebook=notebook,
        team_id=notebook.team_id,
        revision=notebook.app_revision,
        markdown=restore.markdown if restore else markdown,
        variables=restore.variables if restore else notebook.variables or [],
        title=restore.title if restore else notebook.title or "",
        layout=layout,
    )


def validate_release_sources(notebook: Notebook, markdown: str, layout: dict[str, Any]) -> None:
    sources = {
        block.node_id
        for block in iter_markdown_blocks(
            markdown, max_prose_blocks=MAX_ADDRESSABLE_PROSE_BLOCKS, group_anchored_prose=True
        )
    }
    variables = {variable["name"] for variable in notebook.variables or []}
    cells = extract_cells(notebook.content)
    build_dependency_edges(cells)
    annotate_run_state(cells, notebook.team_id, notebook)
    states = {cell.node_id: cell for cell in cells}
    problems = []
    for block in layout["blocks"]:
        name = block.get("title") or block["id"]
        if block["kind"] == "input" and block["variable"] not in variables:
            problems.append(f"{name}: choose an existing notebook variable.")
        if block["kind"] != "cell":
            continue
        node_id = block["node_id"]
        if node_id not in sources:
            problems.append(f"{name}: the source cell is missing.")
        elif (
            block.get("display") != "source"
            and (cell := states.get(node_id))
            and cell.cell_type in ("sql", "python")
            and cell.status != "done"
        ):
            problems.append(f"{name}: run the notebook to refresh this result ({cell.status}).")
    if problems:
        raise ValidationError({"app_published": problems})
