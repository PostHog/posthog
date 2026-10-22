from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import MetricsDashboardVariable, MetricsHistogramQuery, MetricsQuery, MetricsQueryFilter

from posthog.models import Team

from products.dashboards.backend.facade.dashboard_creation import DashboardTileSnapshot, NewInsightTile, TileLayout
from products.metrics.backend.dashboard_import.catalog import CatalogEntry, MetricCatalog
from products.metrics.backend.dashboard_import.spec import (
    BuilderClause,
    BuilderFilter,
    BuilderQuery,
    DisplaySpec,
    GridLayout,
)
from products.metrics.backend.suggested_dashboards.bank import curated_templates
from products.metrics.backend.suggested_dashboards.checks import AttributeStats, ProjectChecks, variable_candidates
from products.metrics.backend.suggested_dashboards.dashboards import (
    attribute_variable,
    build_tiles,
    panels_from_tiles,
    referenced_variables,
)
from products.metrics.backend.suggested_dashboards.discovery import _signed
from products.metrics.backend.suggested_dashboards.generation import _convert
from products.metrics.backend.suggested_dashboards.llm import ModelFailed, ask_model
from products.metrics.backend.suggested_dashboards.matching import match_template
from products.metrics.backend.suggested_dashboards.spec import (
    DraftPanel,
    DraftVariable,
    EvaluationAnswer,
    TemplatePanel,
)
from products.metrics.backend.variables import filter_referenced_names

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


def _panel(
    key: str, *names: str, x: int = 0, y: int = 0, w: int = 6, h: int = 4, kind: str = "MetricsQuery"
) -> TemplatePanel:
    return TemplatePanel(key=key, title=key, query=_query(*names, kind=kind), layout=GridLayout(x=x, y=y, w=w, h=h))


class _Checks(ProjectChecks):
    def __init__(
        self,
        value_counts: dict[str, int] | None,
        pairs: frozenset[frozenset[str]] = frozenset(),
        errors: dict[str, str] | None = None,
    ) -> None:
        super().__init__(Team(id=1), [], value_counts, deadline=0)
        self._pairs = pairs
        self._errors = errors or {}

    def one_to_one(self, first: str, second: str) -> bool:
        return frozenset({first, second}) in self._pairs

    def run_errors(self, queries: Any, variables: Any) -> dict[str, str]:
        return {key: error for key, error in self._errors.items() if key in queries}


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
        for variable in template.definition.variables:
            MetricsDashboardVariable.model_validate(variable)
        queries = [panel.query for panel in template.definition.panels if panel.query is not None]
        assert referenced_variables(queries, template.definition.variables) == template.definition.variables

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
        panels = [
            _panel("orders", "orders_total", x=0, w=4),
            _panel("missing", "missing_total", x=4, w=4),
            _panel("queue", "queue_depth", x=8, w=4),
            _panel("latency", "request_duration_seconds", y=4, w=12, kind="MetricsHistogramQuery"),
        ]
        built = build_tiles(panels, CATALOG)
        kept_in_place = build_tiles(panels, CATALOG, refill=False)

        assert built.dropped == ("missing",)
        insights = [tile for tile in built.tiles if isinstance(tile, NewInsightTile)]
        assert [(tile.name, tile.layout.x, tile.layout.w) for tile in insights] == [
            ("orders", 0, 6),
            ("queue", 6, 6),
            ("latency", 0, 12),
        ]
        assert insights[0].query["clauses"][0]["metricType"] == "sum"
        assert insights[2].query["metricType"] == "histogram"
        assert [
            (tile.name, tile.layout.x, tile.layout.w)
            for tile in kept_in_place.tiles
            if isinstance(tile, NewInsightTile)
        ] == [("orders", 0, 4), ("queue", 8, 4), ("latency", 0, 12)]

    def test_build_tiles_keeps_the_columns_of_a_tile_beside_a_taller_one(self) -> None:
        built = build_tiles(
            [
                _panel("tall", "orders_total", w=6, h=8),
                _panel("upper", "queue_depth", x=6),
                _panel("lower", "queue_depth", x=6, y=4),
                _panel("missing", "missing_total", y=8, w=12),
            ],
            CATALOG,
        )

        insights = [tile for tile in built.tiles if isinstance(tile, NewInsightTile)]
        assert [(tile.name, tile.layout.x, tile.layout.y, tile.layout.w) for tile in insights] == [
            ("tall", 0, 0, 6),
            ("upper", 6, 0, 6),
            ("lower", 6, 4, 6),
        ]

    def test_an_answer_that_does_not_parse_is_a_failed_model_call(self) -> None:
        client = MagicMock()
        # A truncated answer fails the schema while the SDK parses it.
        client.messages.parse.side_effect = lambda **kwargs: EvaluationAnswer.model_validate_json('{"suggested": [')
        with (
            patch("products.metrics.backend.suggested_dashboards.llm.build_anthropic_client", return_value=client),
            self.assertRaises(ModelFailed),
        ):
            ask_model(team_id=1, stage="evaluate", system="", content=[], answer_type=EvaluationAnswer)

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
                DashboardTileSnapshot(tile_id=4, layout=None, name="Added", query=metrics_query),
            ]
        )

        assert [(panel.title, panel.text) for panel in panels] == [
            ("Orders", None),
            ("", "## Notes"),
            ("Added", None),
        ]
        assert (panels[2].layout.x, panels[2].layout.y) == (0, 5)
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

    def test_referenced_variables_keeps_the_variables_of_the_queries_and_of_their_options(self) -> None:
        query = _query("orders_total")
        query["clauses"][0]["filters"] = [{"key": "instance", "op": "eq", "value": "$instance"}]
        instance = {
            **attribute_variable(name="instance", label="Instance", attribute="instance"),
            "query": "SELECT DISTINCT attribute_value FROM posthog.metric_attributes WHERE attribute_key = $job",
        }
        job = attribute_variable(name="job", label="Job", attribute="job")
        unused = attribute_variable(name="unused", label="Unused", attribute="unused")

        assert referenced_variables([query], [job, unused, instance]) == [job, instance]
        assert referenced_variables([_query("orders_total")], [job, unused, instance]) == []

    @parameterized.expand(
        [
            ("attribute", "instance", False),
            ("several_values", "env", True),
            ("service", "service_name", False),
        ]
    )
    def test_a_drafted_variable_selects_all_and_lists_the_values_of_the_opening_project(
        self, _name: str, attribute: str, multi: bool
    ) -> None:
        converted = _convert(
            [self._draft("orders", "orders_total", 0, filters=[BuilderFilter(key=attribute, op="eq", value="$scope")])],
            Team(id=1),
            CATALOG,
            variables=[DraftVariable(name="scope", label="Scope", attribute=attribute, multi=multi)],
            attributes={"orders_total": ["instance", "env"]},
        )

        assert len(converted.variables) == 1
        variable = MetricsDashboardVariable.model_validate(converted.variables[0])
        assert variable.current is not None
        assert (variable.current.values, variable.current.all) == ([], True)
        assert (variable.includeAll, variable.multi) == (True, multi)
        assert (variable.query or "").startswith(
            "SELECT DISTINCT service_name FROM posthog.metric_names"
            if attribute == "service_name"
            else "SELECT DISTINCT attribute_value FROM posthog.metric_attributes"
        )

    def test_convert_drops_variables_with_unknown_attributes_or_no_panel(self) -> None:
        converted = _convert(
            [
                self._draft(
                    "orders",
                    "orders_total",
                    0,
                    filters=[
                        BuilderFilter(key="instance", op="eq", value="$instance"),
                        BuilderFilter(key="host", op="eq", value="$host"),
                    ],
                ),
                self._draft("queue", "queue_depth", 8),
            ],
            Team(id=1),
            CATALOG,
            variables=[
                DraftVariable(name="instance", label="Instance", attribute="instance"),
                DraftVariable(name="host", label="Host", attribute="host.name"),
                DraftVariable(name="job", label="Job", attribute="job"),
                DraftVariable(name="__interval", label="Interval", attribute="instance"),
            ],
            attributes={"orders_total": ["instance", "job"]},
        )

        assert [variable["name"] for variable in converted.variables] == ["instance"]
        assert [variable.name for variable in converted.accepted_variables] == ["instance"]
        orders = converted.panels[0].query
        assert orders is not None
        assert filter_referenced_names(
            MetricsQueryFilter.model_validate(item) for item in orders["clauses"][0]["filters"]
        ) == ["instance"]

    @parameterized.expand(
        [
            ("one_value", ["instance"], {"instance": 1}, frozenset(), []),
            ("several_values", ["instance"], {"instance": 3}, frozenset(), ["instance"]),
            ("unread_profile", ["instance"], None, frozenset(), ["instance"]),
            (
                "one_to_one",
                ["instance", "host"],
                {"instance": 3, "host": 3},
                {frozenset({"instance", "host"})},
                ["instance"],
            ),
            ("independent", ["instance", "host"], {"instance": 3, "host": 3}, frozenset(), ["instance", "host"]),
            ("profiled_attribute_outside_the_keys", ["env"], {"env": 3}, frozenset(), ["env"]),
        ]
    )
    def test_convert_keeps_variables_with_several_values_that_select_different_things(
        self,
        _name: str,
        attributes: list[str],
        value_counts: dict[str, int] | None,
        pairs: frozenset[frozenset[str]],
        kept: list[str],
    ) -> None:
        converted = _convert(
            [
                self._draft(
                    "orders",
                    "orders_total",
                    0,
                    filters=[BuilderFilter(key=attribute, op="eq", value=f"${attribute}") for attribute in attributes],
                )
            ],
            Team(id=1),
            CATALOG,
            variables=[DraftVariable(name=attribute, label=attribute, attribute=attribute) for attribute in attributes],
            attributes={"orders_total": ["instance", "host"]},
            checks=_Checks(value_counts, frozenset(pairs)),
        )

        assert [variable["name"] for variable in converted.variables] == kept
        orders = converted.panels[0].query
        assert orders is not None
        assert (
            filter_referenced_names(
                MetricsQueryFilter.model_validate(item) for item in orders["clauses"][0].get("filters", [])
            )
            == kept
        )

    def test_convert_filters_on_the_kept_variable_where_a_panel_filtered_on_a_replaced_one(self) -> None:
        converted = _convert(
            [
                self._draft(
                    "orders", "orders_total", 0, filters=[BuilderFilter(key="instance", op="eq", value="$instance")]
                ),
                self._draft(
                    "queue", "queue_depth", 4, filters=[BuilderFilter(key="host", op="regex", value="${host:regex}")]
                ),
                self._draft(
                    "cache", "orders_total", 8, filters=[BuilderFilter(key="service.name", op="eq", value="$service")]
                ),
            ],
            Team(id=1),
            CATALOG,
            variables=[
                DraftVariable(name="instance", label="Instance", attribute="instance"),
                DraftVariable(name="host", label="Host", attribute="host"),
                DraftVariable(name="service", label="Service", attribute="service_name"),
            ],
            attributes={"orders_total": ["instance", "host"]},
            checks=_Checks(
                {"instance": 3, "host": 3, "service_name": 3},
                frozenset({frozenset({"instance", "host"}), frozenset({"instance", "service_name"})}),
            ),
        )

        assert [variable["name"] for variable in converted.variables] == ["instance"]
        queue, cache = (panel.query for panel in converted.panels[1:])
        assert queue is not None and cache is not None
        assert queue["clauses"][0]["filters"] == [{"key": "instance", "op": "regex", "value": "${instance:regex}"}]
        assert cache["clauses"][0]["filters"] == [{"key": "instance", "op": "eq", "value": "$instance"}]

    def test_convert_drops_the_panels_whose_query_fails_to_run(self) -> None:
        converted = _convert(
            [self._draft("orders", "orders_total", 0), self._draft("queue", "queue_depth", 4)],
            Team(id=1),
            CATALOG,
            checks=_Checks({}, errors={"queue": "Bad regex"}),
        )

        assert [panel.key for panel in converted.panels] == ["orders"]
        assert converted.dropped == ("queue: Bad regex",)

    @parameterized.expand(
        [
            ("one_value", 1, 3, False),
            ("few_values_on_most_metrics", 5, 3, True),
            ("on_half_of_the_metrics", 5, 2, False),
            ("too_many_values", 21, 4, False),
            ("at_the_limit", 20, 4, True),
        ]
    )
    def test_variable_candidates_have_a_few_values_on_most_metrics(
        self, _name: str, value_count: int, metric_count: int, candidate: bool
    ) -> None:
        profile = {"env": AttributeStats(value_count=value_count, metric_count=metric_count)}

        assert (variable_candidates(profile, 4) == ["env"]) is candidate

    @staticmethod
    def _draft(key: str, metric: str, x: int, filters: list[BuilderFilter] | None = None) -> DraftPanel:
        return DraftPanel(
            key=key,
            title=key,
            query=BuilderQuery(
                clauses=[BuilderClause(name="a", metric_name=metric, aggregation="rate", filters=filters or [])]
            ),
            display=DisplaySpec(type="line"),
            layout=GridLayout(x=x, y=0, w=4, h=4),
        )

    @parameterized.expand([(0, 0), (2**63 - 1, 2**63 - 1), (2**63, -(2**63)), (2**64 - 1, -1)])
    def test_unsigned_fingerprint_fits_a_signed_column(self, unsigned: int, signed: int) -> None:
        assert _signed(unsigned) == signed
