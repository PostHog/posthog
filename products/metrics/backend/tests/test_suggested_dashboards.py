from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import MetricsHistogramQuery, MetricsQuery

from posthog.models import Team

from products.dashboards.backend.facade.dashboard_creation import DashboardTileSnapshot, NewInsightTile, TileLayout
from products.metrics.backend.dashboard_import.catalog import CatalogEntry, MetricCatalog
from products.metrics.backend.dashboard_import.spec import BuilderClause, BuilderQuery, DisplaySpec, GridLayout
from products.metrics.backend.suggested_dashboards.bank import curated_templates
from products.metrics.backend.suggested_dashboards.dashboards import build_tiles, panels_from_tiles
from products.metrics.backend.suggested_dashboards.discovery import _signed
from products.metrics.backend.suggested_dashboards.generation import _convert
from products.metrics.backend.suggested_dashboards.matching import match_template
from products.metrics.backend.suggested_dashboards.spec import DraftPanel, TemplatePanel

CATALOG = MetricCatalog(
    [
        CatalogEntry(name="orders_total", metric_type="sum", unit=""),
        CatalogEntry(name="queue_depth", metric_type="gauge", unit=""),
        CatalogEntry(name="request_duration_seconds", metric_type="histogram", unit="s"),
    ],
    complete=True,
)


def _query(*names: str, kind: str = "MetricsQuery") -> dict[str, Any]:
    if kind == "MetricsHistogramQuery":
        return {"kind": kind, "metricName": names[0]}
    return {
        "kind": kind,
        "clauses": [
            {"name": f"c{index}", "metricName": name, "aggregation": "avg"} for index, name in enumerate(names)
        ],
        "display": {"type": "line"},
    }


def _panel(key: str, *names: str, x: int = 0, y: int = 0, w: int = 6, kind: str = "MetricsQuery") -> TemplatePanel:
    return TemplatePanel(key=key, title=key, query=_query(*names, kind=kind), layout=GridLayout(x=x, y=y, w=w, h=4))


class TestSuggestedDashboards(SimpleTestCase):
    @parameterized.expand([(template.key,) for template in curated_templates()])
    def test_bank_template_queries_are_valid_and_fit_the_grid(self, key: str) -> None:
        template = next(item for item in curated_templates() if item.key == key)
        boxes: set[tuple[int, int]] = set()
        for panel in template.definition.panels:
            assert panel.query is not None
            schema = MetricsHistogramQuery if panel.query["kind"] == "MetricsHistogramQuery" else MetricsQuery
            schema.model_validate(panel.query)
            layout = panel.layout
            assert 0 <= layout.x and layout.x + layout.w <= 12
            cells = {(layout.x + dx, layout.y + dy) for dx in range(layout.w) for dy in range(layout.h)}
            assert not boxes & cells, f"{panel.key} overlaps another panel"
            boxes |= cells

    @parameterized.expand(
        [
            ("every_metric_present", [("a", "orders_total"), ("b", "queue_depth")], 2, True),
            ("one_panel_misses_a_metric", [("a", "orders_total"), ("b", "queue_depth", "missing_total")], 1, False),
            (
                "histogram_series_name_resolves",
                [("a", "request_duration_seconds_bucket"), ("b", "orders_total")],
                2,
                True,
            ),
            ("nothing_present", [("a", "missing_total"), ("b", "other_missing")], 0, False),
        ]
    )
    def test_match_counts_panels_whose_metrics_all_exist(
        self, _name: str, panels: list[tuple[str, ...]], supported: int, strong: bool
    ) -> None:
        match = match_template("t", [_panel(key, *names) for key, *names in panels], CATALOG)
        assert match.supported_panel_count == supported
        assert match.is_strong is strong

    def test_build_tiles_drops_panels_without_data_and_fills_their_row(self) -> None:
        built = build_tiles(
            [
                _panel("orders", "orders_total", x=0, w=4),
                _panel("missing", "missing_total", x=4, w=4),
                _panel("queue", "queue_depth", x=8, w=4),
                _panel("latency", "request_duration_seconds", y=4, w=12, kind="MetricsHistogramQuery"),
            ],
            CATALOG,
        )

        assert built.dropped == ("missing",)
        insights = [tile for tile in built.tiles if isinstance(tile, NewInsightTile)]
        assert [(tile.name, tile.layout.x, tile.layout.w) for tile in insights] == [
            ("orders", 0, 6),
            ("queue", 6, 6),
            ("latency", 0, 12),
        ]
        assert insights[0].query["clauses"][0]["metricType"] == "sum"
        assert insights[2].query["metricType"] == "histogram"

    def test_panels_from_tiles_keeps_metrics_tiles_and_drops_team_metric_types(self) -> None:
        metrics_query: dict[str, Any] = {**_query("orders_total"), "dateRange": {"date_from": "-1h"}}
        metrics_query["clauses"][0]["metricType"] = "sum"
        panels = panels_from_tiles(
            [
                DashboardTileSnapshot(
                    tile_id=1, layout=TileLayout(x=0, y=0, w=6, h=4), name="Orders", query=metrics_query
                ),
                DashboardTileSnapshot(
                    tile_id=2, layout=TileLayout(x=6, y=0, w=6, h=4), name="Trend", query={"kind": "InsightVizNode"}
                ),
                DashboardTileSnapshot(tile_id=3, layout=TileLayout(x=0, y=4, w=12, h=1), body="## Notes"),
            ]
        )

        assert [(panel.title, panel.text) for panel in panels] == [("Orders", None), ("", "## Notes")]
        assert panels[0].query is not None
        assert "metricType" not in panels[0].query["clauses"][0]
        assert "dateRange" not in panels[0].query

    def test_convert_drops_unknown_metrics_and_overlapping_boxes(self) -> None:
        def draft(key: str, metric: str, x: int) -> DraftPanel:
            return DraftPanel(
                key=key,
                title=key,
                query=BuilderQuery(clauses=[BuilderClause(name="a", metric_name=metric, aggregation="rate")]),
                display=DisplaySpec(type="line"),
                layout=GridLayout(x=x, y=0, w=8, h=4),
            )

        converted = _convert(
            [
                draft("orders", "orders_total", 0),
                draft("invented", "invented_total", 0),
                draft("queue", "queue_depth", 4),
            ],
            Team(id=1),
            CATALOG,
        )

        assert converted.dropped == ("invented",)
        assert [panel.key for panel in converted.panels] == ["orders", "queue"]
        first, second = (panel.layout for panel in converted.panels)
        assert first.x + first.w <= second.x or first.y + first.h <= second.y

    @parameterized.expand([(0, 0), (2**63 - 1, 2**63 - 1), (2**63, -(2**63)), (2**64 - 1, -1)])
    def test_unsigned_fingerprint_fits_a_signed_column(self, unsigned: int, signed: int) -> None:
        assert _signed(unsigned) == signed
