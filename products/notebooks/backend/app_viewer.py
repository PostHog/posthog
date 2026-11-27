from collections import defaultdict
from typing import Any
from uuid import UUID

from rest_framework.exceptions import NotFound, ValidationError

from posthog.hogql.errors import ExposedHogQLError

from posthog.exceptions import Conflict

from products.notebooks.backend.app_draft import draft_release_from_notebook
from products.notebooks.backend.app_releases import read_release
from products.notebooks.backend.facade.contracts import AppRelease, AppViewerQuery, AppWidgetSlot
from products.notebooks.backend.markdown_collab import get_markdown_notebook_markdown
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import Notebook, NotebookWidgetInstance
from products.notebooks.backend.sql_v2_references import SQLV2ReferenceError, resolve_sql_v2_references
from products.notebooks.backend.sql_v2_serializers import NotebookVariableSerializer
from products.notebooks.backend.sql_v2_state import (
    NotebookCellState,
    build_dependency_edges,
    extract_cells,
    get_dataframe_owners,
)
from products.notebooks.backend.sql_v2_variables import (
    NotebookVariable,
    NotebookVariableError,
    NotebookVariableValue,
    build_notebook_variables,
    substitute_hogql_variables,
)
from products.notebooks.backend.widgets import widget_node_ids, widget_source_name


def plan_viewer_queries(
    team_id: int, notebook_id: UUID, revision: int, inputs: dict[str, NotebookVariableValue]
) -> list[AppViewerQuery]:
    release = read_release(team_id, notebook_id)
    if release is None:
        raise NotFound()
    if release.revision != revision:
        raise Conflict("A new version of this app is available. Reload the app and try again.")
    return _plan_layout_queries(team_id, notebook_id, release, inputs)


def plan_draft_queries(
    team_id: int, notebook_id: UUID, revision: int, layout: dict[str, Any], inputs: dict[str, NotebookVariableValue]
) -> list[AppViewerQuery]:
    notebook = Notebook.objects.get(team_id=team_id, pk=notebook_id)
    draft = draft_release_from_notebook(notebook, revision, layout, get_markdown_notebook_markdown(notebook.content))
    return _plan_layout_queries(team_id, notebook_id, draft, inputs)


def _plan_layout_queries(
    team_id: int, notebook_id: UUID, release: AppRelease, inputs: dict[str, NotebookVariableValue]
) -> list[AppViewerQuery]:
    visible = {
        block["node_id"]
        for block in release.layout["blocks"]
        if block["kind"] == "cell" and block.get("display") != "source"
    }
    visible_widgets = visible & widget_node_ids(build_markdown_notebook_content(release.markdown))
    instances = (
        NotebookWidgetInstance.objects.for_team(team_id)
        .filter(notebook_id=notebook_id, node_id__in=visible_widgets)
        .select_related("pinned_version", "widget__current_version")
    )
    widget_sources: dict[str, list[AppWidgetSlot]] = defaultdict(list)
    for instance in instances:
        version = instance.pinned_version or instance.widget.current_version
        if version is None:
            continue
        for item in version.input_contract:
            if isinstance(item, dict) and isinstance(item.get("slot"), str):
                source = widget_source_name(instance, item)
                widget_sources[source].append(
                    AppWidgetSlot(node_id=instance.node_id, version_id=version.id, slot=item["slot"])
                )
    return resolve_viewer_queries(release, inputs, widget_sources)


def resolve_viewer_queries(
    release: AppRelease,
    inputs: dict[str, NotebookVariableValue],
    widget_sources: dict[str, list[AppWidgetSlot]] | None = None,
) -> list[AppViewerQuery]:
    defaults = build_notebook_variables(release.variables)
    variables = viewer_variables(release, inputs)
    displayed = {
        block["node_id"]
        for block in release.layout["blocks"]
        if block["kind"] == "cell" and block.get("display") != "source"
    }
    cells = extract_cells(build_markdown_notebook_content(release.markdown))
    build_dependency_edges(cells)
    by_id = {cell.node_id: cell for cell in cells}
    unsupported = [cell for cell in cells if cell.cell_type != "sql" or cell.connection_id or cell.send_raw_query]
    excluded = {cell.node_id for cell in unsupported}
    while unsupported:
        for dependent in unsupported.pop().dependents:
            if dependent not in excluded:
                excluded.add(dependent)
                unsupported.append(by_id[dependent])
    owners = get_dataframe_owners(cells)
    slots_by_node = {owners[name]: slots for name, slots in (widget_sources or {}).items() if name in owners}
    displayed.update(slots_by_node)
    displayed = (displayed & by_id.keys()) - excluded
    required = set(displayed)
    pending = list(displayed)
    while pending:
        for upstream in by_id[pending.pop()].depends_on:
            if upstream not in required:
                required.add(upstream)
                pending.append(upstream)
    try:
        queries = _bound_queries(by_id, required, displayed, owners, variables)
        published = queries if variables == defaults else _bound_queries(by_id, required, displayed, owners, defaults)
    except (NotebookVariableError, ExposedHogQLError, SQLV2ReferenceError) as error:
        raise ValidationError("Could not prepare the published SQL for these inputs.") from error
    return [
        AppViewerQuery(
            node_id=node_id,
            query=query,
            matches_defaults=published.get(node_id) == query,
            widget_slots=slots_by_node.get(node_id, []),
        )
        for node_id, query in queries.items()
    ]


def viewer_variables(release: AppRelease, inputs: dict[str, NotebookVariableValue]) -> list[NotebookVariable]:
    allowed = {block["variable"] for block in release.layout["blocks"] if block["kind"] == "input"}
    if inputs.keys() - allowed:
        raise ValidationError("Choose a published app input.")
    overrides = NotebookVariableSerializer(
        data=[{**var, "value": inputs[var["name"]]} for var in release.variables if var["name"] in inputs], many=True
    )
    overrides.is_valid(raise_exception=True)
    by_name = {var["name"]: var for var in overrides.validated_data}
    return build_notebook_variables([by_name.get(var["name"], var) for var in release.variables])


def _bound_queries(
    by_id: dict[str, NotebookCellState],
    required: set[str],
    displayed: set[str],
    owners: dict[str, str],
    variables: list[NotebookVariable],
) -> dict[str, str]:
    definitions = {node_id: substitute_hogql_variables(by_id[node_id].code, variables) for node_id in required}
    return {
        node_id: resolve_sql_v2_references(
            definitions[node_id], {name: definitions.get(owner) for name, owner in owners.items() if owner != node_id}
        )
        for node_id in by_id
        if node_id in displayed
    }
