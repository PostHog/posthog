import json
from typing import Any
from uuid import UUID

from django.db.models.fields.json import KeyTransform

from pydantic import JsonValue

from products.notebooks.backend.models import Notebook, NotebookAppRelease, NotebookNodeRun
from products.notebooks.backend.sql_v2_direct import sync_direct_run
from products.notebooks.backend.sql_v2_state import MAX_ADDRESSABLE_PROSE_BLOCKS
from products.notebooks.backend.util import _parse_markdown_component_props, iter_markdown_blocks

MAX_RELEASE_RESULT_BYTES = 8 * 1024 * 1024


def read_published_run_rows(team_id: int, notebook_id: UUID, run_id: UUID) -> list[list[JsonValue]] | None:
    key = str(run_id)
    return (
        NotebookAppRelease.objects.for_team(team_id)
        .filter(notebook_id=notebook_id, sql_rows__has_key=key)
        .order_by("-revision")
        .values_list(KeyTransform(key, "sql_rows"), flat=True)
        .first()
    )


def capture_published_sql_rows(notebook: Notebook, markdown: str, layout: dict[str, Any]) -> dict[str, list[list[Any]]]:
    displayed = {
        block["node_id"] for block in layout["blocks"] if block["kind"] == "cell" and block.get("display") != "source"
    }
    if not displayed:
        return {}
    run_refs = {
        block.node_id: run_id
        for block in iter_markdown_blocks(
            markdown, max_prose_blocks=MAX_ADDRESSABLE_PROSE_BLOCKS, group_anchored_prose=True
        )
        if block.tag_name == "SQLV2" and block.node_id in displayed
        if isinstance(run_id := _parse_markdown_component_props(block.source).get("runId"), str)
    }
    runs = (
        NotebookNodeRun.objects.for_team(notebook.team_id)
        .filter(
            notebook=notebook,
            node_id__in=run_refs,
            id__in=run_refs.values(),
            node_type=NotebookNodeRun.NodeType.HOGQL,
            status=NotebookNodeRun.Status.DONE,
            envelope__has_more=True,
        )
        .only("id", "team_id", "notebook_id", "node_id", "node_type", "status", "created_at")
        .order_by("node_id")
    )
    captured: dict[str, list[list[Any]]] = {}
    remaining = MAX_RELEASE_RESULT_BYTES - 2
    for run in runs:
        key = str(run.pk)
        if key != run_refs[run.node_id]:
            continue
        rows = read_published_run_rows(run.team_id, run.notebook_id, run.id)
        if rows is None:
            rows = sync_direct_run(run)
        if rows is None:
            continue
        size = len(json.dumps({key: rows}, ensure_ascii=False, allow_nan=False).encode())
        if size <= remaining:
            captured[key] = rows
            remaining -= size
    return captured
