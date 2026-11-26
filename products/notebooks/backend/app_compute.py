import json
import secrets
from contextlib import ExitStack
from graphlib import CycleError, TopologicalSorter
from time import monotonic
from typing import Any
from uuid import UUID

from pydantic import JsonValue
from rest_framework.exceptions import NotFound, ValidationError

from posthog.hogql.direct_connection import get_direct_connection_source, raw_query_uses_organization_grant
from posthog.hogql.direct_sql import get_raw_adapter_for_source
from posthog.hogql.direct_sql.raw_sql import parse_direct_statements
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.exceptions import Conflict
from posthog.models import User

from products.notebooks.backend.app_releases import read_release
from products.notebooks.backend.app_viewer import draft_app_release, viewer_variables
from products.notebooks.backend.kernel_runtime import (
    APP_VIEWER_KERNEL_PREFIX,
    APP_VIEWER_MAX_OUTPUT_BYTES,
    KernelRuntimeSession,
    get_kernel_runtime,
)
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import Notebook
from products.notebooks.backend.sql_v2_direct import apply_page_bounds, apply_raw_page_bounds
from products.notebooks.backend.sql_v2_state import NotebookCellState, build_dependency_edges, extract_cells
from products.notebooks.backend.sql_v2_variables import (
    NotebookVariable,
    NotebookVariableError,
    NotebookVariableValue,
    python_variable_bindings,
    reject_variables_in_raw_query,
    substitute_duckdb_variables,
    substitute_hogql_variables,
)

MAX_ROWS = 500
MAX_CELLS = 20


def _cell_chain(cells: list[NotebookCellState], target: str) -> list[NotebookCellState]:
    by_id = {cell.node_id: cell for cell in cells}
    if target not in by_id:
        raise ValidationError("This cell has no runnable source.")
    build_dependency_edges(cells)
    graph: dict[str, list[str]] = {}
    pending = [target]
    while pending:
        node_id = pending.pop()
        if node_id not in graph:
            graph[node_id] = by_id[node_id].depends_on
            pending.extend(graph[node_id])
    if len(graph) > MAX_CELLS:
        raise ValidationError("This calculation needs more than 20 cells. Split it into smaller calculations.")
    try:
        return [by_id[node_id] for node_id in TopologicalSorter(graph).static_order()]
    except CycleError as error:
        raise ValidationError("These cells have a circular dependency.") from error


def _bounded_json(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)
    except ValueError as error:
        raise ValidationError("The result contains a non-finite number. Convert it to null in the source.") from error
    if len(encoded.encode()) > APP_VIEWER_MAX_OUTPUT_BYTES:
        raise ValidationError("The result is too large. Narrow the inputs or aggregate the source data.")
    return encoded


def _execute_python(kernel: KernelRuntimeSession, code: str, deadline: float) -> str:
    remaining = int(deadline - monotonic())
    if remaining <= 0:
        raise ValidationError("The calculation timed out.")
    result = kernel.execute(code, capture_variables=False, timeout=min(remaining, 30))
    if result.status != "ok":
        raise ValidationError((result.stderr or result.error_name or "The calculation failed.")[-3000:])
    text = (result.stdout or "") + str((result.result or {}).get("text/plain", ""))
    _bounded_json(text)
    return text


def run_app_cell(
    team_id: int,
    notebook_id: UUID,
    user: User,
    revision: int,
    node_id: str,
    inputs: dict[str, NotebookVariableValue],
    *,
    draft_layout: dict[str, Any] | None = None,
) -> dict[str, JsonValue]:
    release = (
        draft_app_release(team_id, notebook_id, revision, draft_layout)
        if draft_layout is not None
        else read_release(team_id, notebook_id)
    )
    if release is None:
        raise NotFound()
    if draft_layout is None and release.published_at is None:
        raise Conflict("Ask an editor to publish this app again before running its calculations.")
    if release.revision != revision:
        raise Conflict("The published app changed. Reload before running this cell.")
    if not any(
        block.get("node_id") == node_id and block.get("kind") == "cell" and block.get("display") != "source"
        for block in release.layout["blocks"]
    ):
        raise ValidationError("Choose an output in the published app.")
    variables = viewer_variables(release, inputs)
    chain = _cell_chain(extract_cells(build_markdown_notebook_content(release.markdown)), node_id)
    if any(cell.cell_type not in ("python", "sql") for cell in chain):
        raise ValidationError("This calculation requires an unsupported source. Use Python or a HogQL select query.")
    if any(cell.send_raw_query and not cell.connection_id for cell in chain):
        raise ValidationError("Choose a direct connection for native SQL.")
    if any(cell.connection_id and cell.depends_on for cell in chain):
        raise ValidationError("A connected query cannot read a dataframe from another cell.")
    notebook = Notebook.objects.select_related("team").get(team_id=team_id, pk=notebook_id)
    needs_kernel = any(cell.cell_type == "python" or cell.depends_on for cell in chain)
    with (
        tags_context(product=Product.NOTEBOOKS, feature=Feature.QUERY, team_id=notebook.team_id),
        ExitStack() as cleanup,
    ):
        kernel = None
        deadline = monotonic() + 90
        if needs_kernel:
            scratch = Notebook(
                team=notebook.team,
                short_id=APP_VIEWER_KERNEL_PREFIX + secrets.token_urlsafe(8),
                visibility=Notebook.Visibility.INTERNAL,
            )
            kernel = get_kernel_runtime(scratch, user)
            cleanup.callback(kernel.shutdown)
            _execute_python(
                kernel,
                f"import json, pandas as pd\nglobals().update(json.loads({json.dumps(python_variable_bindings(variables))!r}))",
                deadline,
            )
        result: dict[str, JsonValue] = {}
        for cell in chain:
            try:
                result = _run_cell(cell, notebook, user, variables, kernel, deadline, cell.node_id == node_id)
            except NotebookVariableError as error:
                raise ValidationError(str(error)) from error
        return result


def _run_cell(
    cell: NotebookCellState,
    notebook: Notebook,
    user: User,
    variables: list[NotebookVariable],
    kernel: KernelRuntimeSession | None,
    deadline: float,
    final: bool,
) -> dict[str, JsonValue]:
    if cell.cell_type == "python":
        assert kernel is not None
        text = _execute_python(kernel, cell.code, deadline)
        if cell.dataframe_name and not final:
            name = cell.dataframe_name
            _execute_python(
                kernel,
                f"if isinstance(globals().get({name!r}), pd.DataFrame):\n    duck_save_table({name!r}, globals()[{name!r}])",
                deadline,
            )
        return {"text": text}
    if cell.depends_on:
        assert kernel is not None
        query, parameters = substitute_duckdb_variables(cell.code, variables)
        _execute_python(
            kernel, f"_app_result = duck_execute({query!r}, json.loads({json.dumps(parameters)!r}))", deadline
        )
        if cell.dataframe_name and not final:
            _execute_python(
                kernel,
                f"globals()[{cell.dataframe_name!r}] = _app_result\nduck_save_table({cell.dataframe_name!r}, _app_result)",
                deadline,
            )
        return _kernel_frame(kernel, "_app_result", deadline) if final else {}
    query = (
        _external_query(cell, notebook, user, variables)
        if cell.send_raw_query
        else apply_page_bounds(substitute_hogql_variables(cell.code, variables), MAX_ROWS + 1, 0)
    )
    response = execute_hogql_query(
        query=query,
        team=notebook.team,
        user=user,
        connection_id=cell.connection_id,
        send_raw_query=cell.send_raw_query,
        workload=Workload.ONLINE,
    )
    if response.error:
        raise ValidationError(response.error)
    if len(response.results) > MAX_ROWS:
        raise ValidationError("This calculation reads more than 500 rows. Aggregate the source data or add a limit.")
    frame = {"columns": response.columns or [], "rows": response.results}
    payload = _bounded_json(frame)
    if kernel is not None and cell.dataframe_name and not final:
        name = cell.dataframe_name
        _execute_python(
            kernel,
            f"_app_frame = json.loads({payload!r})\nglobals()[{name!r}] = pd.DataFrame(_app_frame['rows'], columns=_app_frame['columns'])\nduck_save_table({name!r}, globals()[{name!r}])",
            deadline,
        )
    return json.loads(payload)


def _kernel_frame(kernel: KernelRuntimeSession, name: str, deadline: float) -> dict[str, JsonValue]:
    data = _execute_python(
        kernel,
        f"print(json.dumps(notebook_dataframe_page(globals()[{name!r}], limit={MAX_ROWS})))",
        deadline,
    )
    page = json.loads(data)
    if page["row_count"] > MAX_ROWS:
        raise ValidationError("This calculation returns more than 500 rows. Aggregate the result or add a limit.")
    columns = page["columns"]
    return {"columns": columns, "rows": [[row.get(col) for col in columns] for row in page["rows"]]}


def _external_query(cell: NotebookCellState, notebook: Notebook, user: User, variables: list[NotebookVariable]) -> str:
    reject_variables_in_raw_query(cell.code, variables)
    source = get_direct_connection_source(notebook.team, cell.connection_id, user=user, require_pure_direct=True)
    if source is None or raw_query_uses_organization_grant(source):
        raise ValidationError("Choose a direct connection that you can query with your own project access.")
    adapter = get_raw_adapter_for_source(source, team=notebook.team)
    if adapter is None or adapter.engine not in {
        "postgres",
        "mysql",
        "redshift",
        "snowflake",
        "bigquery",
        "motherduck",
        "clickhouse",
        "trino",
    }:
        raise ValidationError("This connection does not support read-only native SQL in apps.")
    if adapter.engine == "postgres":
        statements = parse_direct_statements(cell.code, dialect="postgres")
        if len(statements) != 1 or statements[0].get_type() != "SELECT":
            raise ValidationError("App queries must read rows with SELECT.")
    validated = adapter.prepare_raw_sql(cell.code)
    return apply_raw_page_bounds(validated, MAX_ROWS + 1, 0)
