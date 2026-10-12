"""Convert a Grafana v2 dashboard resource into the classic dashboard JSON model.

Grafana 12 can export a dashboard as a v2 resource (`dashboard.grafana.app/v2alpha1` or `v2beta1`).
It keeps the panels in an `elements` map and their positions in a separate `layout` tree. The
converter rebuilds the classic `panels`, `templating` and `time` fields, so that the classic
parser reads both formats the same way.
"""

from __future__ import annotations

from typing import Any

# Grafana's classic grid has 24 columns.
GRAFANA_COLUMNS = 24
_AUTO_GRID_HEIGHTS = {"short": 5, "standard": 8, "tall": 12}
_AUTO_GRID_COLUMNS = 3

_VARIABLE_TYPES = {
    "QueryVariable": "query",
    "CustomVariable": "custom",
    "ConstantVariable": "constant",
    "TextVariable": "textbox",
    "IntervalVariable": "interval",
    "DatasourceVariable": "datasource",
    "AdhocVariable": "adhoc",
    "GroupByVariable": "groupby",
}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int(value: Any, default: int) -> int:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return int(value)
    return default


def is_v2_spec(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("elements"), dict) and isinstance(value.get("layout"), dict)


def classic_from_v2(spec: dict[str, Any]) -> dict[str, Any]:
    time_settings = _dict(spec.get("timeSettings"))
    converter = _LayoutConverter(_dict(spec.get("elements")))
    converter.convert(_dict(spec.get("layout")))
    return {
        "title": spec.get("title"),
        "description": spec.get("description"),
        "time": {"from": time_settings.get("from"), "to": time_settings.get("to")},
        "templating": {"list": [variable for item in _list(spec.get("variables")) if (variable := _variable(item))]},
        "panels": converter.panels,
    }


def _variable(item: Any) -> dict[str, Any] | None:
    item = _dict(item)
    spec = _dict(item.get("spec"))
    kind = _VARIABLE_TYPES.get(str(item.get("kind")))
    if kind is None or not isinstance(spec.get("name"), str):
        return None
    variable = {**spec, "type": kind}
    if kind == "datasource":
        # A classic datasource variable names its plugin in `query`.
        variable["query"] = spec.get("pluginId")
    elif not isinstance(spec.get("query"), str):
        variable.pop("query", None)
    return variable


def _query_target(query: Any) -> dict[str, Any] | None:
    spec = _dict(_dict(query).get("spec"))
    inner = _dict(spec.get("query"))
    if not inner:
        return None
    # v2beta1 wraps the query as {"kind": "DataQuery", "group": <plugin>}; v2alpha1 uses {"kind": <plugin>}.
    plugin = inner.get("group") if inner.get("kind") == "DataQuery" else inner.get("kind")
    alpha_datasource = _dict(spec.get("datasource"))
    beta_datasource = _dict(inner.get("datasource"))
    return {
        **_dict(inner.get("spec")),
        "refId": spec.get("refId"),
        "hide": bool(spec.get("hidden")),
        "datasource": {
            "type": alpha_datasource.get("type") or plugin,
            "uid": alpha_datasource.get("uid") or beta_datasource.get("name"),
        },
    }


def _panel(element: Any) -> dict[str, Any] | None:
    element = _dict(element)
    spec = _dict(element.get("spec"))
    if element.get("kind") == "LibraryPanel":
        return {"id": spec.get("id"), "title": spec.get("title"), "libraryPanel": _dict(spec.get("libraryPanel"))}
    if element.get("kind") != "Panel":
        return None
    viz = _dict(spec.get("vizConfig"))
    viz_spec = _dict(viz.get("spec"))
    data = _dict(_dict(spec.get("data")).get("spec"))
    return {
        "id": spec.get("id"),
        "type": viz.get("group") if viz.get("kind") == "VizConfig" else viz.get("kind"),
        "title": spec.get("title"),
        "description": spec.get("description"),
        "options": viz_spec.get("options"),
        "fieldConfig": viz_spec.get("fieldConfig"),
        "targets": [target for query in _list(data.get("queries")) if (target := _query_target(query))],
    }


class _LayoutConverter:
    """Walks the layout tree in reading order and gives each panel a classic grid position.

    Sections (rows and tabs) become classic row panels. Each section starts below the previous one, so
    the classic parser sees the same order and the same column spans.
    """

    def __init__(self, elements: dict[str, Any]) -> None:
        self._elements = elements
        self.panels: list[dict[str, Any]] = []
        self._next_y = 0

    def convert(self, layout: dict[str, Any]) -> None:
        kind = layout.get("kind")
        spec = _dict(layout.get("spec"))
        if kind == "GridLayout":
            self._grid(_list(spec.get("items")))
        elif kind == "RowsLayout":
            for row in _list(spec.get("rows")):
                self._section(row, title_key="title")
        elif kind == "TabsLayout":
            for tab in _list(spec.get("tabs")):
                self._section(tab, title_key="title")
        elif kind == "AutoGridLayout":
            self._auto_grid(spec)

    def _section(self, section: Any, *, title_key: str) -> None:
        spec = _dict(_dict(section).get("spec"))
        title = spec.get(title_key) if not spec.get("hideHeader") else None
        self.panels.append(
            {"type": "row", "title": title or "", "gridPos": {"x": 0, "y": self._next_y, "w": 24, "h": 1}}
        )
        self._next_y += 1
        self.convert(_dict(spec.get("layout")))

    def _grid(self, items: list[Any]) -> None:
        start = self._next_y
        for item in items:
            item = _dict(item)
            spec = _dict(item.get("spec"))
            if item.get("kind") == "GridLayoutRow":
                # v2alpha1 keeps rows inside the grid. The children follow the row header.
                self._next_y = max(self._next_y, start + _int(spec.get("y"), 0))
                self._section({"spec": {"title": spec.get("title"), "layout": {}}}, title_key="title")
                self._grid(_list(spec.get("elements")))
                continue
            self._add(item, x=_int(spec.get("x"), 0), y=start + _int(spec.get("y"), 0), w=spec.get("width"))

    def _auto_grid(self, spec: dict[str, Any]) -> None:
        columns = max(_int(spec.get("maxColumnCount"), _AUTO_GRID_COLUMNS), 1)
        width = max(GRAFANA_COLUMNS // columns, 1)
        height = _AUTO_GRID_HEIGHTS.get(str(spec.get("rowHeightMode")), _AUTO_GRID_HEIGHTS["standard"])
        start = self._next_y
        for index, item in enumerate(_list(spec.get("items"))):
            row, column = divmod(index, columns)
            self._add(_dict(item), x=column * width, y=start + row * height, w=width, h=height)

    def _add(self, item: dict[str, Any], *, x: int, y: int, w: Any, h: Any = None) -> None:
        spec = _dict(item.get("spec"))
        name = _dict(spec.get("element")).get("name")
        panel = _panel(self._elements.get(str(name)))
        if panel is None:
            return
        width = _int(w, 12)
        height = _int(h if h is not None else spec.get("height"), 8)
        panel["gridPos"] = {"x": x, "y": y, "w": width, "h": height}
        if _dict(spec.get("repeat")).get("value"):
            panel["repeat"] = _dict(spec.get("repeat")).get("value")
        self.panels.append(panel)
        self._next_y = max(self._next_y, y + height)
