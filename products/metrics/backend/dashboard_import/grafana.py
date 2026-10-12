"""Read a Grafana dashboard JSON model into a dashboard spec.

The parser is deterministic. It flattens rows, maps panel boxes to the 12-column grid, maps panel types,
units, thresholds and reducers, resolves template variables, and rewrites Grafana range variables.
The validator and the agent work from the spec, not from the raw JSON.
"""

from __future__ import annotations

import re
from typing import Any

from products.metrics.backend.dashboard_import.display import (
    axis_bound,
    legacy_thresholds,
    map_reducer,
    map_thresholds,
    map_unit,
)
from products.metrics.backend.dashboard_import.grafana_variables import TemplateVariables
from products.metrics.backend.dashboard_import.layout import (
    MIN_INSIGHT_HEIGHT,
    MIN_INSIGHT_WIDTH,
    GridPacker,
    grafana_columns_to_grid,
    grafana_height_to_rows,
    pixels_to_rows,
)
from products.metrics.backend.dashboard_import.promql_text import (
    drop_match_all_matchers,
    looks_like_logql,
    strip_grafana_ranges,
)
from products.metrics.backend.dashboard_import.spec import (
    GRID_COLUMNS,
    DashboardSpec,
    DisplaySpec,
    DisplayType,
    GridLayout,
    PanelKind,
    PanelSpec,
    Reducer,
    TargetLanguage,
    TargetSpec,
)

MAX_PANELS = 150
MAX_EXPRESSION_LENGTH = 4000
MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 1000
MAX_TEXT_LENGTH = 4000

_KIND_BY_TYPE: dict[str, PanelKind] = {
    "timeseries": "timeseries",
    "graph": "timeseries",
    "trend": "timeseries",
    "xychart": "timeseries",
    "state-timeline": "timeseries",
    "status-history": "timeseries",
    "barchart": "timeseries",
    "histogram": "timeseries",
    "candlestick": "timeseries",
    "stat": "stat",
    "singlestat": "stat",
    "gauge": "gauge",
    "bargauge": "bargauge",
    "piechart": "bargauge",
    "grafana-piechart-panel": "bargauge",
    "table": "table",
    "table-old": "table",
    "heatmap": "heatmap",
    "logs": "logs",
    "traces": "traces",
}

_APPROXIMATED_TYPES: dict[str, str] = {
    "trend": "PostHog shows a trend panel as a line chart.",
    "xychart": "PostHog shows an XY chart as a line chart over time.",
    "state-timeline": "PostHog shows a state timeline as a line chart.",
    "status-history": "PostHog shows a status history as a line chart.",
    "histogram": "PostHog shows a histogram panel as a bar chart over time.",
    "candlestick": "PostHog shows a candlestick panel as a line chart.",
    "piechart": "PostHog shows a pie chart as a bar gauge.",
    "grafana-piechart-panel": "PostHog shows a pie chart as a bar gauge.",
}

_DISPLAY_BY_KIND: dict[PanelKind, DisplayType] = {
    "timeseries": "line",
    "stat": "stat",
    "gauge": "gauge",
    "bargauge": "bargauge",
    "table": "table",
    "heatmap": "heatmap",
    "logs": "table",
    "traces": "table",
}
_REDUCED_KINDS = frozenset({"stat", "gauge", "bargauge", "table"})

_DATASOURCE_NAME_HINTS: tuple[tuple[str, str], ...] = (
    ("loki", "loki"),
    ("tempo", "tempo"),
    ("jaeger", "jaeger"),
    ("zipkin", "zipkin"),
    ("prom", "prometheus"),
    ("mimir", "prometheus"),
    ("thanos", "prometheus"),
    ("cortex", "prometheus"),
    ("victoria", "prometheus"),
)
_TRACE_DATASOURCES = frozenset({"tempo", "jaeger", "zipkin"})

_RELATIVE_TIME = re.compile(r"^now-(\d+)([smhdwMy])(?:/([smhdwMy]))?$")
_ROUNDED_NOW = re.compile(r"^now/([dwMy])$")
# Grafana writes minutes as "m" and months as "M". The date filters use the opposite letters.
_TIME_UNITS = {"s": "s", "m": "M", "h": "h", "d": "d", "w": "w", "M": "m", "y": "y"}
_HTML_TAG = re.compile(r"<[^>]+>")


class GrafanaImportError(ValueError):
    """The input is not a Grafana dashboard that the import can read. The message is safe to show."""


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return int(value)
    return default


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _position(panel: dict[str, Any]) -> tuple[int, int]:
    grid = _dict(panel.get("gridPos"))
    return _int(grid.get("y"), 0), _int(grid.get("x"), 0)


def _pixels(value: Any, default: float) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str) and (match := re.match(r"^\s*(\d+(?:\.\d+)?)", value)):
        return float(match.group(1))
    return default


def relative_date(grafana_from: Any) -> str | None:
    """A Grafana time range start such as "now-6h" as a dashboard date filter such as "-6h"."""
    if not isinstance(grafana_from, str):
        return None
    if match := _RELATIVE_TIME.match(grafana_from):
        amount, unit, rounding = match.groups()
        if rounding is None:
            return f"-{amount}{_TIME_UNITS[unit]}"
        if rounding == unit and unit in "dwMy":
            return f"-{amount}{_TIME_UNITS[unit]}Start"
        return None
    if match := _ROUNDED_NOW.match(grafana_from):
        return f"{_TIME_UNITS[match.group(1)]}Start"
    return None


class GrafanaDashboardParser:
    def __init__(self, raw: Any) -> None:
        self._dashboard, outer = self._unwrap(raw)
        self._inputs = {
            str(item.get("name")): str(item.get("pluginId"))
            for item in _list(self._dashboard.get("__inputs") or outer.get("__inputs"))
            if isinstance(item, dict) and item.get("name") and item.get("pluginId")
        }
        self._elements = _dict(self._dashboard.get("__elements") or outer.get("__elements"))
        templating = _list(_dict(self._dashboard.get("templating")).get("list"))
        self._datasource_variables = {
            str(item.get("name")): str(item.get("query"))
            for item in templating
            if isinstance(item, dict) and item.get("type") == "datasource" and isinstance(item.get("query"), str)
        }
        self._variables = TemplateVariables.from_templating(templating)
        self._has_adhoc_filters = any(isinstance(item, dict) and item.get("type") == "adhoc" for item in templating)
        self._used_keys: set[str] = set()

    @staticmethod
    def _unwrap(raw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(raw, dict):
            raise GrafanaImportError("Paste the dashboard JSON model as one JSON object.")
        api_version = raw.get("apiVersion")
        dashboard: Any = raw
        if isinstance(api_version, str) and api_version.startswith("dashboard.grafana.app/"):
            if "/v2" in api_version:
                raise GrafanaImportError(
                    "This is a Grafana v2 dashboard resource. Export the dashboard as classic JSON and try again."
                )
            dashboard = raw.get("spec")
        elif isinstance(raw.get("dashboard"), dict):
            dashboard = raw["dashboard"]
        if not isinstance(dashboard, dict) or not (
            isinstance(dashboard.get("panels"), list) or isinstance(dashboard.get("rows"), list)
        ):
            raise GrafanaImportError(
                "The JSON has no panels. In Grafana, open the dashboard settings, select JSON Model, and copy all of it."
            )
        return dashboard, raw

    def parse(self) -> DashboardSpec:
        items = self._ordered_items()
        notes: list[str] = []
        if len(items) > MAX_PANELS:
            notes.append(f"The dashboard has {len(items)} panels. The import reads the first {MAX_PANELS}.")
        panels = [self._panel(panel, layout) for panel, layout in items[:MAX_PANELS]]
        if not panels:
            raise GrafanaImportError("The dashboard has no panels to import.")
        time_range = _dict(self._dashboard.get("time"))
        date_from = relative_date(time_range.get("from"))
        if time_range.get("from") and date_from is None:
            notes.append("The dashboard time range is not available, so the dashboard uses the default range.")
        if self._has_adhoc_filters:
            notes.append("Grafana ad hoc filters are not imported.")
        return DashboardSpec(
            title=_text(self._dashboard.get("title"), MAX_TITLE_LENGTH) or "Imported Grafana dashboard",
            description=_text(self._dashboard.get("description"), MAX_DESCRIPTION_LENGTH),
            date_from=date_from,
            panels=panels,
            variables=self._variables.summary(),
            notes=notes,
        )

    def _ordered_items(self) -> list[tuple[dict[str, Any], GridLayout]]:
        packer = GridPacker()
        if not self._dashboard.get("panels") and self._dashboard.get("rows"):
            return self._legacy_rows(packer)
        items: list[tuple[dict[str, Any], GridLayout]] = []
        top_level = [panel for panel in _list(self._dashboard.get("panels")) if isinstance(panel, dict)]
        for panel in sorted(top_level, key=_position):
            if panel.get("type") == "row":
                if _text(panel.get("title"), MAX_TITLE_LENGTH):
                    items.append((panel, packer.place_full_width(h=1)))
                else:
                    packer.start_band()
                if panel.get("collapsed"):
                    children = [child for child in _list(panel.get("panels")) if isinstance(child, dict)]
                    items.extend((child, self._place(packer, child)) for child in sorted(children, key=_position))
                continue
            items.append((panel, self._place(packer, panel)))
        return items

    def _legacy_rows(self, packer: GridPacker) -> list[tuple[dict[str, Any], GridLayout]]:
        items: list[tuple[dict[str, Any], GridLayout]] = []
        for row in _list(self._dashboard.get("rows")):
            if not isinstance(row, dict):
                continue
            title = _text(row.get("title"), MAX_TITLE_LENGTH)
            if row.get("showTitle") and title:
                items.append(({"type": "row", "title": title}, packer.place_full_width(h=1)))
            else:
                packer.start_band()
            height = max(pixels_to_rows(_pixels(row.get("height"), 250)), MIN_INSIGHT_HEIGHT)
            column = 0
            for panel in _list(row.get("panels")):
                if not isinstance(panel, dict):
                    continue
                # The legacy layout already uses a 12-column grid, so spans need no scaling.
                width = min(max(_int(panel.get("span"), GRID_COLUMNS), MIN_INSIGHT_WIDTH), GRID_COLUMNS)
                if column + width > GRID_COLUMNS:
                    packer.start_band()
                    column = 0
                items.append((panel, packer.place(x=column, w=width, h=height)))
                column += width
            packer.start_band()
        return items

    @staticmethod
    def _place(packer: GridPacker, panel: dict[str, Any]) -> GridLayout:
        grid = _dict(panel.get("gridPos"))
        min_width, min_height = (1, 1) if panel.get("type") == "text" else (MIN_INSIGHT_WIDTH, MIN_INSIGHT_HEIGHT)
        return packer.place(
            x=grafana_columns_to_grid(_int(grid.get("x"), 0)),
            w=max(grafana_columns_to_grid(_int(grid.get("w"), 12)), min_width),
            h=max(grafana_height_to_rows(_int(grid.get("h"), 8)), min_height),
        )

    def _key(self, panel: dict[str, Any]) -> str:
        panel_id = panel.get("id")
        key = f"p{panel_id}" if isinstance(panel_id, int) and not isinstance(panel_id, bool) else ""
        if not key or key in self._used_keys:
            key = f"p{len(self._used_keys) + 1}x"
        self._used_keys.add(key)
        return key

    def _library_model(self, panel: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        reference = _dict(panel.get("libraryPanel"))
        if not reference:
            return panel, None
        element = _dict(self._elements.get(str(reference.get("uid"))))
        model = _dict(element.get("model"))
        if not model:
            if panel.get("targets"):
                return panel, None
            return panel, (
                "This library panel is not in the export. "
                "In Grafana, use Export > Export for sharing externally to include library panels."
            )
        return {
            **model,
            "id": panel.get("id"),
            "gridPos": panel.get("gridPos"),
            "title": panel.get("title") or model.get("title"),
        }, None

    def _panel(self, raw: dict[str, Any], layout: GridLayout) -> PanelSpec:
        panel, library_error = self._library_model(raw)
        grafana_type = str(panel.get("type") or "")
        key = self._key(panel)
        title = _text(panel.get("title"), MAX_TITLE_LENGTH)
        description = _text(panel.get("description"), MAX_DESCRIPTION_LENGTH)
        common = {"key": key, "description": description, "grafana_type": grafana_type, "layout": layout}
        if library_error:
            return PanelSpec(**common, title=title or "Library panel", kind="unsupported", skip_reason=library_error)
        if grafana_type == "row":
            return PanelSpec(**common, title=title or "Row", kind="row", text=f"## {title}")
        if grafana_type == "text":
            return self._text_panel(panel, common, title)
        kind = _KIND_BY_TYPE.get(grafana_type)
        if kind is None:
            return PanelSpec(
                **common,
                title=title or "Untitled panel",
                kind="unsupported",
                skip_reason=f'PostHog has no "{grafana_type or "unknown"}" panel.',
            )
        notes: list[str] = []
        if approximation := _APPROXIMATED_TYPES.get(grafana_type):
            notes.append(approximation)
        if panel.get("repeat"):
            notes.append("Grafana repeats this panel for each variable value. The import keeps one panel.")
        if panel.get("transformations"):
            notes.append("Grafana transformations are not imported.")
        display = self._display(panel, kind, grafana_type, notes)
        targets = self._targets(panel, notes)
        return PanelSpec(
            **common,
            title=title or "Untitled panel",
            kind=kind,
            display=display,
            targets=targets,
            notes=list(dict.fromkeys(notes)),
            skip_reason=None if targets else "The panel has no queries.",
        )

    @staticmethod
    def _text_panel(panel: dict[str, Any], common: dict[str, Any], title: str) -> PanelSpec:
        options = _dict(panel.get("options"))
        content = options.get("content") if isinstance(options.get("content"), str) else panel.get("content")
        mode = options.get("mode") or panel.get("mode") or "markdown"
        body = content.strip() if isinstance(content, str) else ""
        notes: list[str] = []
        if mode == "html" and body:
            body = _HTML_TAG.sub("", body).strip()
            notes.append("The HTML content is imported as plain text.")
        if title and body:
            body = f"### {title}\n\n{body}"
        elif title:
            body = f"### {title}"
        if len(body) > MAX_TEXT_LENGTH:
            body = body[:MAX_TEXT_LENGTH]
            notes.append("The text is too long, so the import keeps the start of it.")
        return PanelSpec(
            **common,
            title=title or "Text",
            kind="text",
            text=body or None,
            notes=notes,
            skip_reason=None if body else "The text panel is empty.",
        )

    def _display(self, panel: dict[str, Any], kind: PanelKind, grafana_type: str, notes: list[str]) -> DisplaySpec:
        defaults = _dict(_dict(panel.get("fieldConfig")).get("defaults"))
        custom = _dict(defaults.get("custom"))
        options = _dict(panel.get("options"))
        first_axis = _dict(next(iter(_list(panel.get("yaxes"))), None))

        display_type = _DISPLAY_BY_KIND.get(kind, "line")
        if kind == "timeseries":
            display_type = self._series_style(panel, grafana_type, custom, notes)

        unit_id = defaults.get("unit")
        if grafana_type == "graph":
            unit_id = first_axis.get("format")
        elif grafana_type == "singlestat":
            unit_id = panel.get("format")
        unit, unit_note = map_unit(unit_id)

        reduce: Reducer | None = None
        thresholds = []
        if kind in _REDUCED_KINDS:
            calculation = next(iter(_list(_dict(options.get("reduceOptions")).get("calcs"))), None)
            if grafana_type == "singlestat":
                calculation = panel.get("valueName") or "avg"
            reduce, reducer_note = map_reducer(calculation or "lastNotNull")
            if reducer_note:
                notes.append(reducer_note)
            thresholds = (
                legacy_thresholds(panel.get("thresholds"), panel.get("colors"))
                if grafana_type == "singlestat"
                else map_thresholds(_dict(defaults.get("thresholds")).get("steps"))
            )
        if unit_note:
            notes.append(unit_note)

        if grafana_type == "graph":
            minimum, maximum = axis_bound(first_axis.get("min")), axis_bound(first_axis.get("max"))
            log_scale = _int(first_axis.get("logBase"), 1) > 1
        else:
            minimum, maximum = axis_bound(defaults.get("min")), axis_bound(defaults.get("max"))
            log_scale = _dict(custom.get("scaleDistribution")).get("type") == "log"
        return DisplaySpec(
            type=display_type,
            unit=unit,
            reduce=reduce,
            thresholds=thresholds,
            min=minimum,
            max=maximum,
            log_scale=log_scale,
        )

    @staticmethod
    def _series_style(
        panel: dict[str, Any], grafana_type: str, custom: dict[str, Any], notes: list[str]
    ) -> DisplayType:
        if grafana_type in ("barchart", "histogram"):
            return "bar"
        if grafana_type == "graph":
            if panel.get("bars") and not panel.get("lines", True):
                return "bar"
            return "area" if panel.get("stack") and _int(panel.get("fill"), 0) > 0 else "line"
        if custom.get("drawStyle") == "bars":
            return "bar"
        stacking = _dict(custom.get("stacking")).get("mode")
        if stacking == "percent":
            notes.append("Percent stacking is not available, so the panel stacks the raw values.")
        return "area" if stacking in ("normal", "percent") else "line"

    def _datasource_type(self, datasource: Any) -> str | None:
        if isinstance(datasource, dict):
            kind = datasource.get("type")
            if isinstance(kind, str) and kind and not kind.startswith("$"):
                return kind
            return self._datasource_type(datasource.get("uid"))
        if not isinstance(datasource, str) or not datasource.strip():
            return None
        name = datasource.strip()
        if name.startswith("$"):
            variable = name.strip("${}")
            return self._inputs.get(variable) or self._datasource_variables.get(variable)
        lowered = name.lower()
        if lowered in ("-- grafana --", "grafana"):
            return "grafana"
        if lowered in ("-- dashboard --", "dashboard"):
            return "dashboard"
        for hint, kind in _DATASOURCE_NAME_HINTS:
            if hint in lowered:
                return kind
        return None

    def _targets(self, panel: dict[str, Any], notes: list[str]) -> list[TargetSpec]:
        panel_datasource = self._datasource_type(panel.get("datasource"))
        grafana_type = str(panel.get("type") or "")
        targets: list[TargetSpec] = []
        hidden = False
        for index, target in enumerate(_list(panel.get("targets"))):
            if not isinstance(target, dict):
                continue
            if target.get("hide"):
                hidden = True
                continue
            ref_id = str(target.get("refId") or chr(ord("A") + index % 26))
            datasource = self._datasource_type(target.get("datasource")) or panel_datasource
            if datasource == "__expr__":
                notes.append("Grafana server-side expressions are not imported.")
                continue
            expression = next(
                (
                    value.strip()
                    for field in ("expr", "query", "rawSql", "target", "expression")
                    if isinstance(value := target.get(field), str) and value.strip()
                ),
                "",
            )
            if not expression:
                continue
            if len(expression) > MAX_EXPRESSION_LENGTH:
                notes.append(f"Query {ref_id} is too long to import.")
                continue
            language = self._language(datasource, target, expression, grafana_type)
            substituted, unresolved = self._variables.substitute(expression)
            if language == "promql":
                rewrite = strip_grafana_ranges(substituted)
                substituted = drop_match_all_matchers(rewrite.expr)
                if rewrite.changed_meaning:
                    notes.append("A $__range window shows per-step values, not one total for the dashboard range.")
            notes.extend(f"The variable ${name} has no saved value." for name in unresolved)
            legend = target.get("legendFormat")
            targets.append(
                TargetSpec(
                    ref_id=ref_id,
                    language=language,
                    datasource_type=datasource,
                    expr=substituted,
                    original_expr=expression,
                    legend=legend if isinstance(legend, str) and legend else None,
                    unresolved_variables=unresolved,
                )
            )
        if hidden:
            notes.append("Hidden queries are not imported.")
        return targets

    @staticmethod
    def _language(datasource: str | None, target: dict[str, Any], expression: str, grafana_type: str) -> TargetLanguage:
        if datasource == "loki" or grafana_type == "logs":
            return "logql"
        if datasource in _TRACE_DATASOURCES or grafana_type == "traces":
            return "traceql"
        if datasource == "prometheus" or (datasource is None and "expr" in target):
            return "logql" if looks_like_logql(expression) else "promql"
        return "other"
