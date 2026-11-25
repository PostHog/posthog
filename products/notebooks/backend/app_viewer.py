from uuid import UUID

from rest_framework.exceptions import NotFound, ValidationError

from posthog.hogql.errors import ExposedHogQLError

from posthog.exceptions import Conflict

from products.notebooks.backend.app_releases import read_release
from products.notebooks.backend.facade.contracts import AppRelease, AppViewerQuery
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.sql_v2_references import SQLV2ReferenceError, resolve_sql_v2_references
from products.notebooks.backend.sql_v2_state import (
    NotebookCellState,
    build_dependency_edges,
    extract_cells,
    get_dataframe_owners,
)
from products.notebooks.backend.sql_v2_variables import (
    NotebookVariable,
    NotebookVariableError,
    build_notebook_variables,
    substitute_hogql_variables,
)


def plan_viewer_queries(
    team_id: int, notebook_id: UUID, revision: int, inputs: dict[str, str | int | float | bool | None]
) -> list[AppViewerQuery]:
    release = read_release(team_id, notebook_id)
    if release is None:
        raise NotFound()
    if release.revision != revision:
        raise Conflict("A new version of this app is available. Reload the app and try again.")
    return resolve_viewer_queries(release, inputs)


def resolve_viewer_queries(
    release: AppRelease, inputs: dict[str, str | int | float | bool | None]
) -> list[AppViewerQuery]:
    allowed = {block["variable"] for block in release.layout["blocks"] if block["kind"] == "input"}
    if inputs.keys() - allowed:
        raise ValidationError("Choose a published app input.")
    defaults = build_notebook_variables(release.variables)
    variables = build_notebook_variables(
        [{**var, "value": inputs.get(var["name"], var.get("value"))} for var in release.variables]
    )
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
    displayed = (displayed & by_id.keys()) - excluded
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
