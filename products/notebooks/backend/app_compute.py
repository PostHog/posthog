import json
import secrets
from contextlib import ExitStack
from graphlib import CycleError, TopologicalSorter
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

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
from products.notebooks.backend.models import Notebook, NotebookWidgetInstance
from products.notebooks.backend.sql_v2_direct import apply_page_bounds, apply_raw_page_bounds
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
    python_variable_bindings,
    reject_variables_in_raw_query,
    substitute_duckdb_variables,
    substitute_hogql_variables,
)
from products.notebooks.backend.widgets import bounded_widget_rows, widget_node_ids, widget_source_name

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
    widget_input: tuple[UUID, str] | None = None,
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
    content = build_markdown_notebook_content(release.markdown)
    cells = extract_cells(content)
    expected_columns = None
    if widget_input:
        if node_id not in widget_node_ids(content):
            raise ValidationError("Choose a widget in this app.")
        source, expected_columns = _widget_source(team_id, notebook_id, node_id, *widget_input)
        owner = get_dataframe_owners(cells).get(source)
        if owner is None:
            raise ValidationError("This widget's dataframe is missing from the app.")
        node_id = owner
    chain = _cell_chain(cells, node_id)
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
                result = _run_cell(
                    cell, notebook, user, variables, kernel, deadline, cell.node_id == node_id, widget_input is not None
                )
            except NotebookVariableError as error:
                raise ValidationError(str(error)) from error
        if widget_input:
            return _widget_frame(result, node_id, widget_input[1], expected_columns)
        return result


def _widget_frame(
    result: dict[str, JsonValue], node_id: str, slot: str, expected_columns: list[dict[str, str]] | None
) -> dict[str, JsonValue]:
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
    return {"widget_frame": json.loads(json.dumps({**frame, "sourceNodeId": node_id}, default=str))}


def _widget_source(
    team_id: int, notebook_id: UUID, node_id: str, version_id: UUID, slot: str
) -> tuple[str, list[dict[str, str]] | None]:
    placement = (
        NotebookWidgetInstance.objects.for_team(team_id)
        .filter(notebook_id=notebook_id, node_id=node_id)
        .select_related("pinned_version", "widget__current_version")
        .first()
    )
    version = (placement.pinned_version or placement.widget.current_version) if placement else None
    if placement is None or version is None or version.id != version_id:
        raise ValidationError("Refresh the app to load the current widget version.")
    for item in version.input_contract:
        if isinstance(item, dict) and item.get("slot") == slot:
            binding = (placement.input_bindings or {}).get(slot)
            transformed = isinstance(binding, dict) and binding.get("hog")
            return widget_source_name(placement, item), None if transformed else item.get("columns", [])
    raise ValidationError("This dataframe is not declared by this widget version.")


def _run_cell(
    cell: NotebookCellState,
    notebook: Notebook,
    user: User,
    variables: list[NotebookVariable],
    kernel: KernelRuntimeSession | None,
    deadline: float,
    final: bool,
    frame_output: bool,
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
        if final and frame_output and cell.dataframe_name:
            return _kernel_frame(kernel, cell.dataframe_name, deadline, include_types=True)
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
        return _kernel_frame(kernel, "_app_result", deadline, include_types=frame_output) if final else {}
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
    if final and frame_output:
        types = dict(response.types or [])
        frame["types"] = [types.get(name, "unknown") for name in response.columns or []]
    payload = _bounded_json(frame)
    if kernel is not None and cell.dataframe_name and not final:
        name = cell.dataframe_name
        _execute_python(
            kernel,
            f"_app_frame = json.loads({payload!r})\nglobals()[{name!r}] = pd.DataFrame(_app_frame['rows'], columns=_app_frame['columns'])\nduck_save_table({name!r}, globals()[{name!r}])",
            deadline,
        )
    return json.loads(payload)


def _kernel_frame(
    kernel: KernelRuntimeSession, name: str, deadline: float, *, include_types: bool
) -> dict[str, JsonValue]:
    data = _execute_python(
        kernel,
        f"_app_df = globals().get({name!r})\n"
        f"_app_page = notebook_dataframe_page(_app_df, limit={MAX_ROWS})\n"
        + (
            "if _app_page is not None:\n    _app_page['types'] = [str(t) for t in pd.DataFrame(_app_df).dtypes]\n"
            if include_types
            else ""
        )
        + "print(json.dumps(_app_page))",
        deadline,
    )
    page = json.loads(data)
    if not isinstance(page, dict):
        raise ValidationError("The source must assign a dataframe to its output variable.")
    if page["row_count"] > MAX_ROWS:
        raise ValidationError("This calculation returns more than 500 rows. Aggregate the result or add a limit.")
    columns = page["columns"]
    return {
        "columns": columns,
        "rows": [[row.get(col) for col in columns] for row in page["rows"]],
        **({"types": page["types"]} if include_types else {}),
    }


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
