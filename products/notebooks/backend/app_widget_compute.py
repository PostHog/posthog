import json
from typing import Any
from uuid import UUID, uuid4

from pydantic import JsonValue
from rest_framework.exceptions import ValidationError

from posthog.hogql.direct_connection import get_direct_connection_source

from posthog.models import User

from products.notebooks.backend.app_compute import (
    app_release_for_output,
    bounded_frame_json,
    run_source_cells,
    source_cell_chain,
)
from products.notebooks.backend.app_viewer import viewer_variables
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import Notebook, NotebookWidgetInstance
from products.notebooks.backend.sql_v2_state import extract_cells, get_dataframe_owners
from products.notebooks.backend.sql_v2_variables import NotebookVariableValue
from products.notebooks.backend.widgets import bounded_widget_rows, widget_node_ids, widget_source_name


def run_widget_cells(
    team_id: int,
    notebook_id: UUID,
    user: User,
    revision: int,
    node_id: str,
    inputs: dict[str, NotebookVariableValue],
    *,
    widget_input: tuple[UUID, str | list[str]],
    draft_layout: dict[str, Any] | None = None,
) -> dict[str, JsonValue]:
    release = app_release_for_output(team_id, notebook_id, revision, node_id, draft_layout)
    content = build_markdown_notebook_content(release.markdown)
    if node_id not in widget_node_ids(content):
        raise ValidationError("Choose a widget in this app.")
    cells = extract_cells(content)
    notebook = Notebook.objects.select_related("team").get(team_id=team_id, pk=notebook_id)
    version_id, selected = widget_input
    names = [selected] if isinstance(selected, str) else selected
    slots, authors = _widget_sources(notebook, node_id, version_id, names, get_dataframe_owners(cells))
    targets = {source for source, _ in slots.values()}
    chain = source_cell_chain(cells, targets)
    private_sources: set[str] = set()
    for cell in chain:
        if cell.cell_type == "python" or cell.connection_id or private_sources.intersection(cell.depends_on):
            private_sources.add(cell.node_id)
    if not targets.issubset(private_sources):
        raise ValidationError("This widget reads native SQL through the app's filtered results.")
    for connection in {cell.connection_id for cell in chain if cell.connection_id}:
        for author in authors:
            if author is None or (
                author.pk != user.pk and get_direct_connection_source(notebook.team, connection, user=author) is None
            ):
                raise ValidationError("The widget and its placement must have access to the connected data source.")
    results = run_source_cells(notebook, user, viewer_variables(release, inputs), chain, targets, include_types=True)
    frames = [_widget_frame(results[source], source, slot, columns) for slot, (source, columns) in slots.items()]
    bounded_frame_json(frames)
    return {"widget_frame": frames[0]} if isinstance(selected, str) else {"widget_frames": frames}


def _widget_frame(
    result: dict[str, JsonValue], node_id: str, slot: str, expected_columns: list[dict[str, str]] | None
) -> JsonValue:
    columns = result.get("columns")
    types = result.get("types")
    rows = result.get("rows")
    if (
        not isinstance(columns, list)
        or not isinstance(types, list)
        or not isinstance(rows, list)
        or len(columns) != len(types)
    ):
        raise ValidationError("This cell must return a dataframe with named columns.")
    schema = [{"name": str(name), "type": str(dtype)} for name, dtype in zip(columns, types, strict=True)]
    if expected_columns is not None and (
        len(expected_columns) != len(schema)
        or any(
            declared.get("name") != actual["name"] or declared.get("type") not in ("unknown", actual["type"])
            for declared, actual in zip(expected_columns, schema, strict=True)
        )
    ):
        raise ValidationError("The dataframe columns changed. Update the widget input to use this result.")
    frame = bounded_widget_rows(
        name=slot,
        run_id=uuid4(),
        columns=schema,
        candidates=rows,
        total_row_count=len(rows),
        offset=0,
    )
    if frame["truncated"]:
        raise ValidationError("The widget dataframe is too large. Narrow the inputs or aggregate the source data.")
    return json.loads(json.dumps({**frame, "sourceNodeId": node_id}, default=str))


def _widget_sources(
    notebook: Notebook, node_id: str, version_id: UUID, names: list[str], owners: dict[str, str]
) -> tuple[dict[str, tuple[str, list[dict[str, str]] | None]], list[User | None]]:
    placement = (
        NotebookWidgetInstance.objects.for_team(notebook.team_id)
        .filter(notebook_id=notebook.pk, node_id=node_id)
        .select_related("created_by", "pinned_version__created_by", "widget__current_version__created_by")
        .first()
    )
    version = (placement.pinned_version or placement.widget.current_version) if placement else None
    if placement is None or version is None or version.id != version_id:
        raise ValidationError("Refresh the app to load the current widget version.")
    contract = {item["slot"]: item for item in version.input_contract if isinstance(item, dict) and "slot" in item}
    slots: dict[str, tuple[str, list[dict[str, str]] | None]] = {}
    for slot in names:
        if slot not in contract:
            raise ValidationError("This dataframe is not declared by this widget version.")
        item = contract[slot]
        owner = owners.get(widget_source_name(placement, item))
        if owner is None:
            raise ValidationError("This widget's dataframe is missing from the app.")
        binding = (placement.input_bindings or {}).get(slot)
        transformed = isinstance(binding, dict) and binding.get("hog")
        slots[slot] = (owner, None if transformed else item.get("columns", []))
    return slots, [placement.created_by, version.created_by]
