import datetime as dt

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from clickhouse_driver.errors import NetworkError

from posthog.clickhouse.query_tagging import get_query_tag_value, tags_context

from products.metrics.backend.hogql_queries.metrics_query_runner import MetricsQueryRunner
from products.metrics.backend.suggested_dashboards.checks import (
    ProjectChecks,
    _run,
    attribute_profile,
    one_to_one,
    variable_candidates,
)
from products.metrics.backend.suggested_dashboards.dashboards import attribute_variable
from products.metrics.backend.tests._seeder import seed_metric, truncate_metrics_tables

METRICS = ["orders_total", "queue_depth", "cache_hits"]


class TestSuggestedDashboardChecks(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        truncate_metrics_tables()
        now = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)
        for metric, labels in [
            ("orders_total", {"env": "prod", "host": "h1", "instance": "i1", "zone": "z1"}),
            ("orders_total", {"env": "prod", "host": "h2", "instance": "i2", "zone": "z2"}),
            ("orders_total", {"env": "dev", "host": "h3", "instance": "i3", "zone": "z3"}),
            ("queue_depth", {"env": "dev", "host": "h1", "instance": "i1", "zone": "z1"}),
            ("cache_hits", {"region": "eu", "zone": "z4"}),
        ]:
            seed_metric(team_id=self.team.id, metric_name=metric, points=[(now, 1.0)], labels=labels)

    def test_profile_counts_values_and_metrics_of_each_attribute(self) -> None:
        profile = attribute_profile(self.team, METRICS)

        assert {key: (stats.value_count, stats.metric_count) for key, stats in profile.items()} == {
            "env": (2, 2),
            "host": (3, 2),
            "instance": (3, 2),
            "region": (1, 1),
            "zone": (4, 3),
            "service_name": (1, 3),
        }
        assert variable_candidates(profile, len(METRICS)) == ["zone", "env", "host", "instance"]

    def test_one_to_one_finds_attributes_that_select_the_same_series(self) -> None:
        assert one_to_one(self.team, METRICS, "host", "instance")
        assert not one_to_one(self.team, METRICS, "env", "host")
        # Only zone selects the cache_hits series.
        assert not one_to_one(self.team, METRICS, "host", "zone")

    def test_run_errors_reports_only_the_queries_that_fail(self) -> None:
        def query(op: str, value: str) -> dict:
            return {
                "kind": "MetricsQuery",
                "clauses": [
                    {
                        "name": "a",
                        "metricName": "queue_depth",
                        "aggregation": "avg",
                        "filters": [{"key": "host", "op": op, "value": value}],
                    }
                ],
            }

        checks = ProjectChecks(self.team, METRICS, None, deadline=30)
        errors = checks.run_errors(
            {"fine": query("eq", "$host"), "broken": query("eq", "$missing")},
            [attribute_variable(name="host", label="Host", attribute="host")],
        )

        assert list(errors) == ["broken"]

    def test_a_transient_failure_propagates_and_a_late_run_leaves_the_panel_unchecked(self) -> None:
        query = {"kind": "MetricsQuery", "clauses": [{"name": "a", "metricName": "queue_depth", "aggregation": "avg"}]}
        checks = ProjectChecks(self.team, METRICS, None, deadline=30)

        with (
            patch.object(MetricsQueryRunner, "calculate", side_effect=NetworkError("connection reset")),
            pytest.raises(NetworkError),
        ):
            checks.run_errors({"a": query}, [])
        assert _run(self.team, {"kind": "MetricsQuery", "clauses": []}, [], timeout=30, start_by=0) is None

    def test_each_run_keeps_the_query_tags_of_the_caller(self) -> None:
        query = {"kind": "MetricsQuery", "clauses": [{"name": "a", "metricName": "queue_depth", "aggregation": "avg"}]}
        seen: list[object] = []

        with (
            tags_context(team_id=4242),
            patch.object(
                MetricsQueryRunner, "calculate", side_effect=lambda: seen.append(get_query_tag_value("team_id"))
            ),
        ):
            ProjectChecks(self.team, METRICS, None, deadline=30).run_errors({"a": query, "b": query}, [])

        assert seen == [4242, 4242]
