import ast
import json
import secrets
from contextlib import ExitStack
from graphlib import CycleError, TopologicalSorter
from time import monotonic
from typing import Any
from uuid import UUID

from pydantic import JsonValue
from rest_framework.exceptions import NotFound, ValidationError

from posthog.hogql.constants import HogQLGlobalSettings
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
from products.notebooks.backend.facade.contracts import AppRelease
from products.notebooks.backend.kernel_runtime import (
    APP_VIEWER_KERNEL_PREFIX,
    APP_VIEWER_MAX_OUTPUT_BYTES,
    KernelRuntimeSession,
    get_kernel_runtime,
)
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import Notebook
from products.notebooks.backend.sandbox.kernel.envelope import DATAFRAME_TYPE_CHECKS
from products.notebooks.backend.sql_v2_direct import apply_page_bounds, apply_raw_page_bounds
from products.notebooks.backend.sql_v2_references import SQLV2ReferenceError, resolve_sql_v2_references
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
from products.tasks.backend.facade.sandbox import SandboxOutputTooLarge, SandboxTimeoutError

MAX_ROWS = 500
MAX_CELLS = 20


def source_cell_chain(cells: list[NotebookCellState], targets: set[str]) -> list[NotebookCellState]:
    by_id = {cell.node_id: cell for cell in cells}
    if not targets or not targets.issubset(by_id):
        raise ValidationError("This cell has no runnable source.")
    build_dependency_edges(cells)
    graph: dict[str, list[str]] = {}
    pending = list(targets)
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


def bounded_frame_json(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)
    except ValueError as error:
        raise ValidationError("The result contains a non-finite number. Convert it to null in the source.") from error
    if len(encoded.encode()) > APP_VIEWER_MAX_OUTPUT_BYTES:
        raise ValidationError("The result is too large. Narrow the inputs or aggregate the source data.")
    return encoded


def _remaining_seconds(deadline: float) -> int:
    remaining = int(deadline - monotonic())
    if remaining <= 0:
        raise ValidationError("The calculation timed out.")
    return remaining


def _execute_python(kernel: KernelRuntimeSession, code: str, deadline: float) -> str:
    try:
        result = kernel.execute(code, capture_variables=False, timeout=min(_remaining_seconds(deadline), 30))
    except SandboxOutputTooLarge as error:
        raise ValidationError("The result is too large. Narrow the inputs or aggregate the source data.") from error
    except (TimeoutError, SandboxTimeoutError) as error:
        raise ValidationError("The calculation timed out.") from error
    if result.status == "timeout":
        raise ValidationError("The calculation timed out.")
    if result.status != "ok":
        raise ValidationError((result.stderr or result.error_name or "The calculation failed.")[-3000:])
    text = (result.stdout or "") + str((result.result or {}).get("text/plain", ""))
    bounded_frame_json(text)
    return text


def app_release_for_output(
    team_id: int, notebook_id: UUID, revision: int, node_id: str, draft_layout: dict[str, Any] | None
) -> AppRelease:
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
    return release


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
    release = app_release_for_output(team_id, notebook_id, revision, node_id, draft_layout)
    notebook = Notebook.objects.select_related("team").get(team_id=team_id, pk=notebook_id)
    cells = extract_cells(build_markdown_notebook_content(release.markdown))
    targets = {node_id}
    results = run_source_cells(
        notebook, user, viewer_variables(release, inputs), source_cell_chain(cells, targets), targets
    )
    return results[node_id]


def run_source_cells(
    notebook: Notebook,
    user: User,
    variables: list[NotebookVariable],
    chain: list[NotebookCellState],
    targets: set[str],
    *,
    include_types: bool = False,
) -> dict[str, dict[str, JsonValue]]:
    if any(cell.cell_type not in ("python", "sql") for cell in chain):
        raise ValidationError("This calculation requires an unsupported source. Use Python or a HogQL select query.")
    if any(cell.send_raw_query and not cell.connection_id for cell in chain):
        raise ValidationError("Choose a direct connection for native SQL.")
    if any(cell.connection_id and cell.depends_on for cell in chain):
        raise ValidationError("A connected query cannot read a dataframe from another cell.")
    local_frames: set[str] = set()
    kernel_cells: set[str] = set()
    materialize = set(targets)
    upstream: set[str] = set()
    for cell in chain:
        if cell.cell_type == "python" or local_frames.intersection(cell.depends_on):
            kernel_cells.add(cell.node_id)
            materialize.update(cell.depends_on)
            upstream.update(cell.depends_on)
        if cell.node_id in kernel_cells or cell.connection_id:
            local_frames.add(cell.node_id)
    hogql_definitions: dict[str, str | None] = {}
    with (
        tags_context(product=Product.NOTEBOOKS, feature=Feature.QUERY, team_id=notebook.team_id),
        ExitStack() as cleanup,
    ):
        kernel = None
        deadline = monotonic() + 90
        if kernel_cells:
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
        results: dict[str, dict[str, JsonValue]] = {}
        for cell in chain:
            try:
                _remaining_seconds(deadline)
                if cell.node_id in kernel_cells:
                    assert kernel is not None
                    results[cell.node_id] = _run_kernel_cell(
                        cell,
                        variables,
                        kernel,
                        deadline,
                        cell.node_id not in upstream,
                        include_types and cell.node_id in targets,
                    )
                    continue
                if cell.send_raw_query:
                    query = _external_query(cell, notebook, user, variables)
                else:
                    code = substitute_hogql_variables(cell.code, variables)
                    if cell.node_id not in materialize:
                        hogql_definitions[cell.dataframe_name] = code
                        continue
                    query = apply_page_bounds(resolve_sql_v2_references(code, hogql_definitions), MAX_ROWS + 1, 0)
                    if not cell.connection_id:
                        hogql_definitions[cell.dataframe_name] = code
                results[cell.node_id] = _run_sql_cell(
                    cell,
                    query,
                    notebook,
                    user,
                    kernel,
                    deadline,
                    cell.node_id not in upstream,
                    include_types and cell.node_id in targets,
                )
            except (NotebookVariableError, SQLV2ReferenceError) as error:
                raise ValidationError(str(error)) from error
        return results


def _python_cell_code(code: str) -> tuple[str, bool]:
    try:
        module = ast.parse(code)
    except SyntaxError:
        return code, False
    if not module.body or not isinstance(module.body[-1], ast.Expr):
        return code, False
    expression = module.body[-1]
    assignment = ast.Assign(targets=[ast.Name(id="_app_last", ctx=ast.Store())], value=expression.value)
    module.body[-1:] = [ast.copy_location(assignment, expression), ast.Expr(ast.Name(id="_app_last", ctx=ast.Load()))]
    return ast.unparse(ast.fix_missing_locations(module)), True


def _run_kernel_cell(
    cell: NotebookCellState,
    variables: list[NotebookVariable],
    kernel: KernelRuntimeSession,
    deadline: float,
    final: bool,
    include_types: bool,
) -> dict[str, JsonValue]:
    name = cell.dataframe_name
    if cell.cell_type == "python":
        code, has_last_expression = _python_cell_code(cell.code)
        text = _execute_python(kernel, code, deadline)
        if not name:
            return {"text": text}
        bind_frame = f"_app_result = globals().get({name!r})"
        if has_last_expression:
            bind_frame += (
                "\nif isinstance(_app_last, pd.DataFrame):\n    _app_result = _app_last"
                "\nelif isinstance(_app_last, pd.Series):\n    _app_result = _app_last.to_frame()"
            )
        _execute_python(kernel, bind_frame, deadline)
    else:
        text = ""
        query, parameters = substitute_duckdb_variables(cell.code, variables)
        _execute_python(
            kernel,
            f"_app_relation = _duckdb_connection.sql({query!r}, params=json.loads({json.dumps(parameters)!r}))\n"
            f"_app_result = _app_relation.limit({MAX_ROWS + 1}).df()",
            deadline,
        )
    frame = _kernel_frame(kernel, "_app_result", deadline, include_types)
    if frame is None:
        return {"text": text}
    if name and not final:
        _execute_python(
            kernel,
            f"globals()[{name!r}] = _app_result\nduck_save_table({name!r}, _app_result)",
            deadline,
        )
    return frame


def _run_sql_cell(
    cell: NotebookCellState,
    query: str,
    notebook: Notebook,
    user: User,
    kernel: KernelRuntimeSession | None,
    deadline: float,
    final: bool,
    include_types: bool,
) -> dict[str, JsonValue]:
    response = execute_hogql_query(
        query=query,
        team=notebook.team,
        user=user,
        connection_id=cell.connection_id,
        send_raw_query=cell.send_raw_query,
        settings=HogQLGlobalSettings(max_execution_time=_remaining_seconds(deadline)),
        workload=Workload.ONLINE,
    )
    if response.error:
        raise ValidationError(response.error)
    if len(response.results) > MAX_ROWS:
        raise ValidationError("This calculation reads more than 500 rows. Aggregate the source data or add a limit.")
    frame = {"columns": response.columns or [], "rows": response.results}
    if include_types:
        types = dict(response.types or [])
        frame["types"] = [types.get(name, "unknown") for name in response.columns or []]
    payload = bounded_frame_json(frame)
    if kernel is not None and cell.dataframe_name and not final:
        name = cell.dataframe_name
        _execute_python(
            kernel,
            f"_app_frame = json.loads({payload!r})\nglobals()[{name!r}] = pd.DataFrame(_app_frame['rows'], columns=_app_frame['columns'])\nduck_save_table({name!r}, globals()[{name!r}])",
            deadline,
        )
    return json.loads(payload)


def _kernel_frame(
    kernel: KernelRuntimeSession, name: str, deadline: float, include_types: bool
) -> dict[str, JsonValue] | None:
    data = _execute_python(
        kernel,
        (
            f"_app_page = notebook_dataframe_page(globals()[{name!r}], limit={MAX_ROWS})\n"
            f"if _app_page is not None:\n    _app_page['types'] = [next((name for check, name in {DATAFRAME_TYPE_CHECKS!r} if getattr(pd.api.types, check)(dtype)), 'String') for dtype in globals()[{name!r}].dtypes]\n"
            "print(json.dumps(_app_page))"
            if include_types
            else f"print(json.dumps(notebook_dataframe_page(globals()[{name!r}], limit={MAX_ROWS})))"
        ),
        deadline,
    )
    page = json.loads(data)
    if page is None:
        return None
    if page["row_count"] > MAX_ROWS:
        raise ValidationError("This calculation returns more than 500 rows. Aggregate the result or add a limit.")
    columns = page["columns"]
    result: dict[str, JsonValue] = {
        "columns": columns,
        "rows": [[row.get(col) for col in columns] for row in page["rows"]],
    }
    if include_types:
        result["types"] = page["types"]
    return result


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
