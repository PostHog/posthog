from uuid import UUID

from rest_framework.exceptions import NotFound, ValidationError

from posthog.hogql.errors import ExposedHogQLError

from posthog.exceptions import Conflict

from products.notebooks.backend.app_release_results import app_result_node_ids
from products.notebooks.backend.app_releases import read_release, unsupported_viewer_cells
from products.notebooks.backend.facade.contracts import AppRelease, AppViewerQuery
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
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
    notebook_date_range_is_reversed,
    substitute_hogql_variables,
)


def plan_viewer_queries(
    team_id: int, notebook_id: UUID, revision: int, inputs: dict[str, NotebookVariableValue]
) -> list[AppViewerQuery]:
    release = read_release(team_id, notebook_id)
    if release is None:
        raise NotFound()
    if release.revision != revision:
        raise Conflict("A new version of this app is available. Reload the app and try again.")
    return resolve_viewer_queries(release, inputs)


def resolve_viewer_queries(release: AppRelease, inputs: dict[str, NotebookVariableValue]) -> list[AppViewerQuery]:
    controls = [block for block in release.layout["blocks"] if block["kind"] == "input"]
    allowed = {block["variable"] for block in controls}
    ranges = [block for block in controls if block.get("input_kind") == "date_range"]
    allowed.update(block["end_variable"] for block in ranges if block.get("end_variable"))
    if inputs.keys() - allowed:
        raise ValidationError("Choose a published app input.")
    defaults = build_notebook_variables(release.variables)
    overrides = NotebookVariableSerializer(
        data=[{**var, "value": inputs[var["name"]]} for var in release.variables if var["name"] in inputs], many=True
    )
    overrides.is_valid(raise_exception=True)
    by_name = {var["name"]: var for var in overrides.validated_data}
    variables = build_notebook_variables([by_name.get(var["name"], var) for var in release.variables])
    dates = {var.name: var.value for var in variables}
    for block in ranges:
        start_date, end_date = dates.get(block["variable"]), dates.get(block.get("end_variable", ""))
        if notebook_date_range_is_reversed(start_date, end_date):
            raise ValidationError("Choose an end date on or after the start date.")
    displayed = app_result_node_ids(release.layout)
    cells = extract_cells(build_markdown_notebook_content(release.markdown))
    build_dependency_edges(cells)
    by_id = {cell.node_id: cell for cell in cells}
    displayed = (displayed & by_id.keys()) - unsupported_viewer_cells(by_id)
    required = set(displayed)
    pending = list(displayed)
    while pending:
        for upstream in by_id[pending.pop()].depends_on:
            if upstream not in required:
                required.add(upstream)
                pending.append(upstream)
    owners = get_dataframe_owners(cells)
    try:
        queries = _bound_queries(by_id, required, displayed, owners, variables)
        published = queries if variables == defaults else _bound_queries(by_id, required, displayed, owners, defaults)
    except (NotebookVariableError, ExposedHogQLError, SQLV2ReferenceError) as error:
        raise ValidationError("Could not prepare the published SQL for these inputs.") from error
    return [
        AppViewerQuery(node_id=node_id, query=query, matches_defaults=published.get(node_id) == query)
        for node_id, query in queries.items()
    ]


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
