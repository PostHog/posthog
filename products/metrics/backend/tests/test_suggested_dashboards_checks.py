import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from products.metrics.backend.suggested_dashboards.checks import (
    ProjectChecks,
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
            ("orders_total", {"env": "prod", "host": "h1", "instance": "i1"}),
            ("orders_total", {"env": "prod", "host": "h2", "instance": "i2"}),
            ("orders_total", {"env": "dev", "host": "h3", "instance": "i3"}),
            ("queue_depth", {"env": "dev", "host": "h1", "instance": "i1"}),
            ("cache_hits", {"region": "eu"}),
        ]:
            seed_metric(team_id=self.team.id, metric_name=metric, points=[(now, 1.0)], labels=labels)

    def test_profile_counts_values_and_metrics_of_each_attribute(self) -> None:
        profile = attribute_profile(self.team, METRICS)

        assert {key: (stats.value_count, stats.metric_count) for key, stats in profile.items()} == {
            "env": (2, 2),
            "host": (3, 2),
            "instance": (3, 2),
            "region": (1, 1),
            "service_name": (1, 3),
        }
        assert variable_candidates(profile, len(METRICS)) == ["env", "host", "instance"]

    def test_one_to_one_finds_attributes_that_select_the_same_series(self) -> None:
        assert one_to_one(self.team, METRICS, "host", "instance")
        assert not one_to_one(self.team, METRICS, "env", "host")

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
