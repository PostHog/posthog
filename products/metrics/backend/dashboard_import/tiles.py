"""Turns checked panel queries into the insight queries and text tiles of the new dashboard."""

from __future__ import annotations

from typing import Any

from posthog.schema import ChartDisplayType, DataVisualizationNode, MetricsHistogramQuery, MetricsQuery

from products.metrics.backend.dashboard_import.catalog import HISTOGRAM_TYPES, MetricCatalog
from products.metrics.backend.dashboard_import.layout import MIN_INSIGHT_HEIGHT, MIN_INSIGHT_WIDTH
from products.metrics.backend.dashboard_import.spec import DisplaySpec, DisplayType, GridLayout, PanelQuery, TileDraft
from products.metrics.backend.dashboard_import.validation import PanelValidator

MAX_INSIGHT_NAME_LENGTH = 400
DEFAULT_SQL_DATE_FROM = "-24h"

_SQL_DISPLAY: dict[DisplayType, ChartDisplayType] = {
    "line": ChartDisplayType.ACTIONS_LINE_GRAPH,
    "area": ChartDisplayType.ACTIONS_AREA_GRAPH,
    "bar": ChartDisplayType.ACTIONS_BAR,
    "stat": ChartDisplayType.BOLD_NUMBER,
    "gauge": ChartDisplayType.BOLD_NUMBER,
    "bargauge": ChartDisplayType.ACTIONS_BAR,
    "table": ChartDisplayType.ACTIONS_TABLE,
    "heatmap": ChartDisplayType.ACTIONS_LINE_GRAPH,
}


def display_settings(display: DisplaySpec) -> dict[str, Any]:
    # A heatmap needs a histogram query. On a MetricsQuery it draws as a line chart.
    settings: dict[str, Any] = {"type": "line" if display.type == "heatmap" else display.type}
    if display.unit:
        settings["unit"] = display.unit
    if display.reduce:
        settings["reduce"] = display.reduce
    if display.thresholds:
        settings["thresholds"] = [{"color": item.color, "value": item.value} for item in display.thresholds]
    y_axis: dict[str, Any] = {}
    if display.min is not None:
        y_axis["min"] = display.min
        # The axis ignores `min` while it starts at zero.
        y_axis["startAtZero"] = display.min == 0
    if display.max is not None:
        y_axis["max"] = display.max
    if display.log_scale:
        y_axis["scale"] = "log"
    if y_axis:
        settings["yAxis"] = y_axis
    return settings


def insight_query(
    query: PanelQuery,
    display: DisplaySpec,
    *,
    catalog: MetricCatalog,
    validator: PanelValidator,
    date_from: str | None,
) -> dict[str, Any]:
    """The insight query for a checked panel query. It stays minimal, as the editor would save it, after it passes the query schema."""
    if query.language == "promql":
        node: dict[str, Any] = {
            "kind": "MetricsQuery",
            "language": "promql",
            "promql": query.promql,
            "clauses": [],
            "display": display_settings(display),
        }
        MetricsQuery.model_validate(node)
        return node
    if query.language == "builder":
        assert query.builder is not None
        clauses = []
        for clause in query.builder.clauses:
            contract = validator.clause_contract(clause)
            item: dict[str, Any] = {
                "name": contract.name,
                "metricName": contract.metric_name,
                "aggregation": contract.aggregation.value,
            }
            if contract.metric_type is not None:
                item["metricType"] = contract.metric_type.value
            if contract.quantile is not None:
                item["quantile"] = contract.quantile
            if contract.filters:
                item["filters"] = [{"key": f.key, "op": f.op.value, "value": f.value} for f in contract.filters]
            if contract.group_by:
                item["groupBy"] = [{"key": group.key} for group in contract.group_by]
            clauses.append(item)
        node = {"kind": "MetricsQuery", "clauses": clauses, "display": display_settings(display)}
        if query.builder.formula:
            node["formula"] = query.builder.formula
        MetricsQuery.model_validate(node)
        return node
    if query.language == "histogram":
        entry = catalog.resolve(query.histogram_metric or "")
        assert entry is not None
        node = {"kind": "MetricsHistogramQuery", "metricName": entry.name}
        if entry.metric_type in HISTOGRAM_TYPES:
            node["metricType"] = entry.metric_type
        if display.unit:
            node["unit"] = display.unit
        MetricsHistogramQuery.model_validate(node)
        return node
    node = {
        "kind": "DataVisualizationNode",
        "source": {
            "kind": "HogQLQuery",
            "query": query.hogql,
            "filters": {"dateRange": {"date_from": date_from or DEFAULT_SQL_DATE_FROM}},
        },
        "display": _SQL_DISPLAY[display.type].value,
    }
    DataVisualizationNode.model_validate(node)
    return node


def insight_tile(*, name: str, description: str, query: dict[str, Any], layout: GridLayout) -> TileDraft:
    return TileDraft(
        kind="insight",
        name=name[:MAX_INSIGHT_NAME_LENGTH] or "Untitled panel",
        description=description,
        query=query,
        layout=layout.clamped(min_w=MIN_INSIGHT_WIDTH, min_h=MIN_INSIGHT_HEIGHT),
    )


def text_tile(*, name: str, text: str, layout: GridLayout) -> TileDraft:
    return TileDraft(kind="text", name=name, text=text, layout=layout.clamped())
