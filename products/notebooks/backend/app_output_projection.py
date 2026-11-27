from typing import Any

from rest_framework import serializers

from products.notebooks.backend.app_viewer import native_app_output_ids
from products.notebooks.backend.facade.contracts import AppOutputTab
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import NotebookAppRelease
from products.notebooks.backend.sql_v2_state import build_dependency_edges, extract_cells
from products.notebooks.backend.util import _parse_markdown_component_props, iter_markdown_blocks


def automatic_chart_columns(result: dict[str, Any], columns: list[str], display: str | None) -> list[str]:
    types = {
        item[0]: item[1].lower()
        for item in result.get("types") or []
        if isinstance(item, list) and len(item) == 2 and all(isinstance(v, str) for v in item)
    }
    if not types:
        for row in result.get("first_page") or []:
            if isinstance(row, list):
                for name, value in zip(columns, row):
                    if value is not None and name not in types:
                        types[name] = "float" if type(value) in (int, float) else "string"
    numeric = [
        name
        for name in columns
        if not any(kind in types.get(name, "") for kind in ("array", "tuple"))
        and any(kind in types.get(name, "") for kind in ("int", "float", "decimal"))
    ]
    if display in ("BoldNumber", "Metric"):
        return numeric[:1] or columns[:1]
    if display == "ScatterPlot":
        return numeric
    dates = [name for name in columns if "date" in types.get(name, "")]
    x_axis = dates[:1] or [name for name in columns if name not in numeric][:1]
    return x_axis + numeric


def output_columns(props: dict[str, Any], columns: list[str]) -> list[str]:
    viz = props.get("vizQuery") or {}
    displayed = columns
    if props.get("outputTab") == "results" or (isinstance(viz, dict) and viz.get("display") == "ActionsTable"):
        table = viz.get("tableSettings") if isinstance(viz, dict) else None
        selected = table.get("columns") if isinstance(table, dict) else None
        if isinstance(selected, list) and selected:
            displayed = [c["column"] for c in selected if isinstance(c, dict) and c.get("column") in columns]
    elif isinstance(viz, dict):
        settings = viz.get("chartSettings") or {}
        axes = [settings.get("xAxis"), *(settings.get("yAxis") or [])] if isinstance(settings, dict) else []
        named = [axis["column"] for axis in axes if isinstance(axis, dict) and axis.get("column") in columns]
        displayed = named
        if isinstance(settings, dict) and "xAxis" not in settings and "yAxis" not in settings:
            displayed = automatic_chart_columns(props["result"], columns, viz.get("display"))
    else:
        displayed = []
    return displayed


def pinned_sql_result(release: NotebookAppRelease, node_id: str, run_id: str | None) -> dict[str, Any] | None:
    data = release.sql_rows or {}
    schema = data.get(f"schema:{run_id}")
    rows = data.get(run_id)
    if not isinstance(schema, dict) or schema.get("node_id") != node_id or not isinstance(rows, list):
        return None
    columns = schema.get("columns")
    if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
        return None
    return {**schema, "first_page": rows}


def app_output_tabs(
    release: NotebookAppRelease, *, tenant_column: str | None = None, tenant_value: str | None = None
) -> list[AppOutputTab]:
    cells = extract_cells(build_markdown_notebook_content(release.markdown))
    build_dependency_edges(cells)
    allowed = native_app_output_ids(cells)
    sql_cells = {
        cell.node_id: _parse_markdown_component_props(cell.source)
        for cell in iter_markdown_blocks(release.markdown, max_prose_blocks=0)
        if cell.tag_name == "SQLV2" and cell.node_id in allowed
    }
    tabs = {tab["id"]: {"title": tab["title"], "blocks": []} for tab in release.layout["tabs"]}
    for block in release.layout["blocks"]:
        tab = tabs.get(block["tab_id"])
        if tab is None:
            continue
        if block["kind"] == "text":
            tab["blocks"].append({"title": block.get("title"), "text": block.get("text")})
            continue
        if block["kind"] != "cell" or block.get("display") == "source":
            continue
        node_id = block.get("node_id")
        props = sql_cells.get(node_id)
        if not props:
            continue
        result = pinned_sql_result(release, node_id, props.get("runId"))
        if result is None:
            if tenant_column is not None:
                raise serializers.ValidationError(
                    "Save and republish the complete SQL results before creating an embed."
                )
            tab["blocks"].append(
                {"title": block.get("title"), "text": "Republish this app to share a verified SQL result."}
            )
            continue
        columns = result["columns"]
        rows = result["first_page"]
        row_count = result.get("row_count")
        partial = isinstance(row_count, int) and len(rows) < row_count
        displayed = output_columns({**props, "result": result}, columns)
        if tenant_column is not None:
            if partial:
                raise serializers.ValidationError(
                    "Save and republish the complete SQL results before creating an embed."
                )
            if columns.count(tenant_column) != 1:
                raise serializers.ValidationError(
                    {"tenant_column": "Every displayed SQL output must include this tenant column exactly once."}
                )
            idx = columns.index(tenant_column)
            rows = [row for row in rows if isinstance(row, list) and len(row) > idx and row[idx] == tenant_value]
        if props.get("outputTab") != "results" and (props.get("vizQuery") or {}).get("display") == "BoldNumber":
            displayed = output_columns({**props, "outputTab": "results"}, columns)[:1]
            rows = rows[:1]
        if tenant_column is not None:
            displayed = [column for column in displayed if column != tenant_column]
        if displayed:
            indexes = [columns.index(column) for column in displayed]
            tab["blocks"].append(
                {
                    "title": block.get("title") or props.get("title"),
                    "columns": displayed,
                    "partial": partial,
                    "rows": [
                        [row[i] if i < len(row) else None for i in indexes] for row in rows if isinstance(row, list)
                    ],
                }
            )
    return [AppOutputTab(title=tab["title"], blocks=tab["blocks"]) for tab in tabs.values()]
