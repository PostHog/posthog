from typing import Any

import pytest

from products.metrics.backend.dashboard_import.display import map_color, map_thresholds, map_unit
from products.metrics.backend.dashboard_import.grafana import GrafanaDashboardParser, GrafanaImportError, relative_date
from products.metrics.backend.dashboard_import.grafana_variables import TemplateVariables
from products.metrics.backend.dashboard_import.promql_text import (
    combine_targets,
    drop_match_all_matchers,
    metric_names,
    strip_grafana_ranges,
)
from products.metrics.backend.dashboard_import.spec import GridLayout, Threshold

DASHBOARD: dict[str, Any] = {
    "title": "Checkout service",
    "time": {"from": "now-6h", "to": "now"},
    "templating": {
        "list": [
            {"name": "job", "type": "query", "current": {"text": "checkout", "value": "checkout"}},
            {
                "name": "instance",
                "type": "query",
                "includeAll": True,
                "allValue": ".*",
                "current": {"text": "All", "value": "$__all"},
            },
            {"name": "route", "type": "custom", "current": {"text": "/a + /b.c", "value": ["/a", "/b.c"]}},
        ]
    },
    "panels": [
        {"id": 1, "type": "row", "title": "Traffic", "gridPos": {"x": 0, "y": 0, "w": 24, "h": 1}},
        {
            "id": 2,
            "type": "timeseries",
            "title": "Request rate",
            "gridPos": {"x": 0, "y": 1, "w": 12, "h": 8},
            "datasource": {"type": "prometheus", "uid": "prom"},
            "fieldConfig": {"defaults": {"unit": "reqps", "custom": {"stacking": {"mode": "normal"}}}},
            "targets": [
                {
                    "refId": "A",
                    "expr": 'sum by (code) (rate(orders_total{job="$job", instance=~"$instance"}[$__rate_interval]))',
                }
            ],
        },
        {
            "id": 3,
            "type": "stat",
            "title": "Error ratio",
            "gridPos": {"x": 12, "y": 1, "w": 6, "h": 4},
            "fieldConfig": {
                "defaults": {
                    "unit": "percentunit",
                    "thresholds": {"steps": [{"color": "green", "value": None}, {"color": "#F2495C", "value": 0.05}]},
                }
            },
            "options": {"reduceOptions": {"calcs": ["mean"]}},
            "targets": [{"refId": "A", "expr": 'sum(rate(order_errors_total{route=~"$route"}[5m]))'}],
        },
        {"id": 4, "type": "news", "title": "Feed", "gridPos": {"x": 18, "y": 1, "w": 6, "h": 4}},
        {
            "id": 5,
            "type": "row",
            "title": "Logs",
            "collapsed": True,
            "gridPos": {"x": 0, "y": 9, "w": 24, "h": 1},
            "panels": [
                {
                    "id": 6,
                    "type": "logs",
                    "title": "Errors",
                    "gridPos": {"x": 0, "y": 10, "w": 24, "h": 8},
                    "datasource": {"type": "loki", "uid": "loki"},
                    "targets": [{"refId": "A", "expr": '{job="$job"} |= "error"'}],
                }
            ],
        },
        {
            "id": 7,
            "type": "text",
            "gridPos": {"x": 0, "y": 19, "w": 8, "h": 3},
            "options": {"mode": "markdown", "content": "Runbook: see the wiki"},
        },
        {
            "id": 8,
            "type": "timeseries",
            "title": "Unknown cluster",
            "gridPos": {"x": 8, "y": 19, "w": 8, "h": 6},
            "targets": [{"refId": "A", "expr": 'up{cluster="$cluster"}'}],
        },
    ],
}


def _overlaps(first: GridLayout, second: GridLayout) -> bool:
    return (
        first.x < second.x + second.w
        and second.x < first.x + first.w
        and first.y < second.y + second.h
        and second.y < first.y + first.h
    )


def test_parses_panels_into_queries_displays_and_a_grid_without_overlaps() -> None:
    spec = GrafanaDashboardParser(DASHBOARD).parse()
    panels = {panel.key: panel for panel in spec.panels}

    assert spec.title == "Checkout service"
    assert spec.date_from == "-6h"
    assert [panel.key for panel in spec.panels] == ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"]
    assert {key: panel.kind for key, panel in panels.items()} == {
        "p1": "row",
        "p2": "timeseries",
        "p3": "stat",
        "p4": "unsupported",
        "p5": "row",
        "p6": "logs",
        "p7": "text",
        "p8": "timeseries",
    }
    assert panels["p2"].targets[0].expr == 'sum by (code) (rate(orders_total{job="checkout"}))'
    assert (panels["p2"].display.type, panels["p2"].display.unit) == ("area", "{req}/s")
    assert panels["p3"].targets[0].expr == 'sum(rate(order_errors_total{route=~"(/a|/b\\\\.c)"}[5m]))'
    assert (panels["p3"].display.unit, panels["p3"].display.reduce) == ("1", "mean")
    assert panels["p3"].display.thresholds == [
        Threshold(color="success", value=-0.95),
        Threshold(color="danger", value=0.05),
    ]
    assert panels["p4"].skip_reason == 'PostHog has no "news" panel.'
    assert panels["p6"].targets[0].language == "logql"
    assert panels["p7"].text == "Runbook: see the wiki"
    assert panels["p8"].targets[0].unresolved_variables == ["cluster"]
    assert "The variable $cluster has no saved value." in panels["p8"].notes

    assert panels["p1"].layout == GridLayout(x=0, y=0, w=12, h=1)
    assert (panels["p2"].layout.x, panels["p2"].layout.w, panels["p2"].layout.h) == (0, 6, 3)
    assert (panels["p3"].layout.x, panels["p3"].layout.w) == (6, 3)
    assert panels["p6"].layout.y > panels["p5"].layout.y
    layouts = [panel.layout for panel in spec.panels]
    assert not any(_overlaps(a, b) for index, a in enumerate(layouts) for b in layouts[index + 1 :])


def test_legacy_rows_place_spans_side_by_side_under_a_title() -> None:
    spec = GrafanaDashboardParser(
        {
            "rows": [
                {
                    "title": "Hosts",
                    "showTitle": True,
                    "height": "250px",
                    "panels": [
                        {"id": 1, "type": "graph", "span": 6, "targets": [{"expr": "node_load1"}]},
                        {"id": 2, "type": "singlestat", "span": 6, "valueName": "current", "targets": [{"expr": "up"}]},
                    ],
                }
            ]
        }
    ).parse()

    header, graph, single_stat = spec.panels
    assert header.layout == GridLayout(x=0, y=0, w=12, h=1)
    assert (graph.layout.x, graph.layout.y, graph.layout.w) == (0, 1, 6)
    assert (single_stat.layout.x, single_stat.layout.y, single_stat.layout.w) == (6, 1, 6)
    assert single_stat.display.reduce == "last"


@pytest.mark.parametrize(
    "raw, expected_title",
    [
        ({"dashboard": {"title": "Wrapped", "panels": [{"type": "text", "options": {"content": "x"}}]}}, "Wrapped"),
        (
            {
                "apiVersion": "dashboard.grafana.app/v1beta1",
                "kind": "Dashboard",
                "spec": {"title": "Resource", "panels": [{"type": "text", "options": {"content": "x"}}]},
            },
            "Resource",
        ),
    ],
)
def test_reads_wrapped_dashboards(raw: dict[str, Any], expected_title: str) -> None:
    assert GrafanaDashboardParser(raw).parse().title == expected_title


@pytest.mark.parametrize(
    "raw, message",
    [
        ([], "one JSON object"),
        ({"title": "No panels"}, "has no panels"),
        ({"apiVersion": "dashboard.grafana.app/v2beta1", "spec": {"elements": {}}}, "v2 dashboard"),
    ],
)
def test_rejects_input_that_is_not_a_classic_dashboard(raw: Any, message: str) -> None:
    with pytest.raises(GrafanaImportError, match=message):
        GrafanaDashboardParser(raw).parse()


@pytest.mark.parametrize(
    "grafana_from, expected",
    [
        ("now-6h", "-6h"),
        ("now-15m", "-15M"),
        ("now-30d", "-30d"),
        ("now-3M", "-3m"),
        ("now/d", "dStart"),
        ("now-1w/w", "-1wStart"),
        ("2026-01-01T00:00:00Z", None),
    ],
)
def test_maps_the_time_range_to_a_date_filter(grafana_from: str, expected: str | None) -> None:
    assert relative_date(grafana_from) == expected


@pytest.mark.parametrize(
    "expr, expected",
    [
        ('sum by (job) (rate(http_requests_total{job="api"}[5m]))', ["http_requests_total"]),
        ("histogram_quantile(0.9, sum by (le) (rate(latency_seconds_bucket[5m])))", ["latency_seconds_bucket"]),
        ("errors_total / on (instance) group_left (version) build_info", ["errors_total", "build_info"]),
        ('{"http.server.duration", "http.route"="/"}', ["http.server.duration"]),
        ('{__name__="up", job="api"}', ["up"]),
        ("sum(up) without (instance) offset 5m", ["up"]),
        ('count_values("version", build_info)', ["build_info"]),
        ('label_replace(up, "dst", "$1", "src", "(.*)")', ["up"]),
        ("max(node_load1) > bool 3", ["node_load1"]),
    ],
)
def test_finds_the_metric_names_of_an_expression(expr: str, expected: list[str]) -> None:
    assert metric_names(expr) == expected


@pytest.mark.parametrize(
    "expr, expected, changed_meaning",
    [
        ("rate(a[$__rate_interval]) + increase(b[${__interval}])", "rate(a) + increase(b)", False),
        ("increase(a[$__range])", "increase(a)", True),
        ("rate(a[5m])", "rate(a[5m])", False),
        ('rate(a{path="[$__interval]"}[1m])', 'rate(a{path="[$__interval]"}[1m])', False),
    ],
)
def test_rewrites_grafana_ranges_to_the_query_step(expr: str, expected: str, changed_meaning: bool) -> None:
    rewrite = strip_grafana_ranges(expr)
    assert (rewrite.expr, rewrite.changed_meaning) == (expected, changed_meaning)


@pytest.mark.parametrize(
    "expr, expected",
    [
        ('up{job=~".*", env="prod"}', 'up{env="prod"}'),
        ('up{job=~".*"}', "up"),
        ('up{job=~".+"}', 'up{job=~".+"}'),
    ],
)
def test_drops_matchers_that_match_everything(expr: str, expected: str) -> None:
    assert drop_match_all_matchers(expr) == expected


def test_joins_several_targets_with_the_clause_label() -> None:
    assert combine_targets([("A", "rate(a)"), ("B", "rate(b)")]) == (
        'label_replace(rate(a), "clause", "A", "", "") or label_replace(rate(b), "clause", "B", "", "")'
    )


@pytest.mark.parametrize(
    "expr, expected",
    [
        ('up{env=~"$env"}', 'up{env=~"(prod|dev)"}'),
        ('up{env="${env:csv}"}', 'up{env="prod,dev"}'),
        ('up{env=~"${env:pipe}"}', 'up{env=~"prod|dev"}'),
    ],
)
def test_all_without_an_all_value_uses_every_option(expr: str, expected: str) -> None:
    variables = TemplateVariables.from_templating(
        [
            {
                "name": "env",
                "includeAll": True,
                "current": {"text": "All", "value": ["$__all"]},
                "options": [{"value": "$__all"}, {"value": "prod"}, {"value": "dev"}],
            }
        ]
    )
    assert variables.substitute(expr) == (expected, [])


@pytest.mark.parametrize(
    "color, token",
    [
        ("dark-green", "success"),
        ("#F2495C", "danger"),
        ("rgb(250, 222, 42)", "warning"),
        ("#5794F2", "blue"),
        ("#808080", "data-color-1"),
        ("transparent", "data-color-1"),
    ],
)
def test_maps_colors_to_theme_tokens(color: str, token: str) -> None:
    assert map_color(color) == token


def test_base_threshold_sits_below_every_other_step() -> None:
    assert map_thresholds([{"color": "red", "value": None}, {"color": "green", "value": 10}]) == [
        Threshold(color="danger", value=9),
        Threshold(color="success", value=10),
    ]


def test_an_unknown_unit_is_dropped_with_a_note() -> None:
    assert map_unit("lengthmm") == (None, 'The unit "lengthmm" is not available, so the panel shows plain numbers.')
