import datetime as dt
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload

from products.metrics.backend.facade.api import run_metric_query
from products.metrics.backend.facade.contracts import MetricFilter, MetricGroupBy, MetricQueryClause, MetricQueryRequest
from products.metrics.backend.facade.enums import AttributeScope, FilterOp, MetricAggregation
from products.metrics.backend.metric_query_runner import MetricQueryRunner, _pick_interval, attribute_field
from products.metrics.backend.tests._seeder import seed_metric


class TestPickInterval:
    @parameterized.expand(
        [
            # 60 buckets at 1 min each
            ("1h_range_picks_minute", dt.timedelta(hours=1), "minute"),
            # 24 buckets, comfortably under the ~60 target
            ("1d_range_picks_hour", dt.timedelta(days=1), "hour"),
            # 30 buckets; finer intervals all exceed the target
            ("30d_range_picks_day", dt.timedelta(days=30), "day"),
        ]
    )
    def test_pick_interval(self, _name: str, delta: dt.timedelta, expected: str) -> None:
        start = dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
        assert _pick_interval(start, start + delta) == expected


class TestMetricQueryRunner(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")

    def test_rejects_unsupported_aggregation(self):
        with self.assertRaises(ValueError):
            MetricQueryRunner(
                team=self.team,
                metric_name="x",
                aggregation="median",
                date_from=timezone.now() - dt.timedelta(hours=1),
                date_to=timezone.now(),
            )

    def test_rejects_inverted_date_range(self):
        now = timezone.now()
        with self.assertRaises(ValueError):
            MetricQueryRunner(
                team=self.team,
                metric_name="x",
                aggregation="sum",
                date_from=now,
                date_to=now - dt.timedelta(hours=1),
            )

    def test_returns_empty_for_no_data(self):
        runner = MetricQueryRunner(
            team=self.team,
            metric_name="http.server.duration",
            aggregation="sum",
            date_from=timezone.now() - dt.timedelta(hours=1),
            date_to=timezone.now(),
        )
        self.assertEqual(runner.run(), [])

    def test_aggregates_sum_per_bucket(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="m1",
            points=[
                (anchor - dt.timedelta(minutes=5), 2.0),
                (anchor - dt.timedelta(minutes=5), 3.0),
                (anchor - dt.timedelta(minutes=20), 4.0),
            ],
        )
        # Different metric — should be filtered out.
        seed_metric(
            team_id=self.team.id,
            metric_name="m2",
            points=[(anchor - dt.timedelta(minutes=5), 99.0)],
        )

        runner = MetricQueryRunner(
            team=self.team,
            metric_name="m1",
            aggregation="sum",
            date_from=anchor - dt.timedelta(hours=1),
            date_to=anchor,
        )
        results = runner.run()

        values_by_bucket = {row["time"]: row["value"] for row in results}
        self.assertEqual(sum(values_by_bucket.values()), 9.0)

    def test_respects_team_isolation(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=99999,
            metric_name="m1",
            points=[(anchor - dt.timedelta(minutes=5), 5.0)],
        )

        runner = MetricQueryRunner(
            team=self.team,
            metric_name="m1",
            aggregation="sum",
            date_from=anchor - dt.timedelta(hours=1),
            date_to=anchor,
        )
        self.assertEqual(runner.run(), [])


class TestMetricsQueryAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")

    def test_query_requires_authentication(self):
        self.client.logout()
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={"query": {"metricName": "m1", "aggregation": "sum", "dateFrom": "2026-01-01T00:00:00Z"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_query_validates_required_fields(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={"query": {"aggregation": "sum", "dateFrom": "2026-01-01T00:00:00Z"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_query_validates_aggregation_choice(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={"query": {"metricName": "m1", "aggregation": "median", "dateFrom": "2026-01-01T00:00:00Z"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_query_returns_aggregated_points(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="m1",
            points=[
                (anchor - dt.timedelta(minutes=10), 1.0),
                (anchor - dt.timedelta(minutes=10), 2.0),
            ],
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={
                "query": {
                    "metricName": "m1",
                    "aggregation": "sum",
                    "dateFrom": (anchor - dt.timedelta(hours=1)).isoformat(),
                    "dateTo": anchor.isoformat(),
                }
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertIn("results", body)
        self.assertEqual(len(body["results"]), 1)
        series = body["results"][0]
        self.assertEqual(series["labels"], {})
        self.assertEqual(series["metric_name"], "m1")
        self.assertEqual(series["clause"], "a")
        self.assertEqual(sum(point["value"] for point in series["points"]), 3.0)


class TestAttributeField(ClickhouseTestMixin, APIBaseTest):
    """End-to-end tests for the `attribute_field` helper.

    The helper builds an AST node; correctness depends on what ClickHouse
    actually returns, so we execute a real query against `posthog.metrics`
    for each scope and assert the resolved value.
    """

    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")

    def _select_attribute(self, expr: ast.Expr, metric_name: str) -> str | None:
        query = parse_select(
            """
                SELECT {expr} AS value FROM posthog.metrics
                WHERE metric_name = {metric_name} LIMIT 1
            """,
            placeholders={"expr": expr, "metric_name": ast.Constant(value=metric_name)},
        )
        assert isinstance(query, ast.SelectQuery)
        response = execute_hogql_query(
            query_type="AttributeFieldTest",
            query=query,
            team=self.team,
            workload=Workload.LOGS,
        )
        if not response.results:
            return None
        return response.results[0][0]

    def test_rejects_unknown_scope(self):
        with self.assertRaises(ValueError):
            attribute_field("container", scope="bogus")  # type: ignore[arg-type]

    def test_resource_scope_reads_resource_attributes(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="m_resource",
            points=[(anchor, 1.0)],
            resource_labels={"service_name": "logs-ingestion"},
        )
        value = self._select_attribute(attribute_field("service_name", scope="resource"), "m_resource")
        self.assertEqual(value, "logs-ingestion")

    def test_attribute_scope_reads_attributes_via_alias(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="m_attribute",
            points=[(anchor, 1.0)],
            labels={"http_method": "POST"},
        )
        value = self._select_attribute(attribute_field("http_method", scope="attribute"), "m_attribute")
        self.assertEqual(value, "POST")

    def test_auto_scope_prefers_resource_when_present(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="m_auto_resource",
            points=[(anchor, 1.0)],
            resource_labels={"container": "capture-logs"},
            labels={"container": "should-not-win"},
        )
        value = self._select_attribute(attribute_field("container"), "m_auto_resource")
        self.assertEqual(value, "capture-logs")

    def test_auto_scope_falls_back_to_attribute_when_resource_empty(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="m_auto_attribute",
            points=[(anchor, 1.0)],
            labels={"endpoint": "/api/projects/2/metrics/query"},
        )
        value = self._select_attribute(attribute_field("endpoint"), "m_auto_attribute")
        self.assertEqual(value, "/api/projects/2/metrics/query")

    def test_auto_scope_returns_empty_when_neither_present(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="m_auto_missing",
            points=[(anchor, 1.0)],
        )
        value = self._select_attribute(attribute_field("nonexistent"), "m_auto_missing")
        self.assertEqual(value, "")


class TestRunMetricQueryFacade(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")

    def _request(self, **overrides):
        anchor = timezone.now().replace(microsecond=0)
        defaults: dict[str, Any] = {
            "clauses": (MetricQueryClause(name="a", metric_name="m1", aggregation=MetricAggregation.SUM),),
            "date_from": anchor - dt.timedelta(hours=1),
            "date_to": anchor,
        }
        defaults.update(overrides)
        return MetricQueryRequest(**defaults)

    def test_single_clause_returns_one_series_with_empty_labels(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="m1",
            points=[(anchor - dt.timedelta(minutes=10), 1.5), (anchor - dt.timedelta(minutes=10), 2.5)],
        )

        series = run_metric_query(team=self.team, request=self._request())

        self.assertEqual(len(series), 1)
        self.assertEqual(series[0].labels, {})
        self.assertEqual(series[0].metric_name, "m1")
        self.assertEqual(series[0].clause, "a")
        self.assertEqual(sum(p.value for p in series[0].points), 4.0)

    def test_quantile_095_maps_to_p95(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric(team_id=self.team.id, metric_name="m1", points=[(anchor - dt.timedelta(minutes=10), 5.0)])

        series = run_metric_query(
            team=self.team,
            request=self._request(
                clauses=(
                    MetricQueryClause(
                        name="a", metric_name="m1", aggregation=MetricAggregation.QUANTILE, quantile=0.95
                    ),
                )
            ),
        )
        self.assertEqual(len(series), 1)

    @parameterized.expand(
        [
            (
                "multi_clause",
                {
                    "clauses": (
                        MetricQueryClause(name="a", metric_name="m1", aggregation=MetricAggregation.SUM),
                        MetricQueryClause(name="b", metric_name="m2", aggregation=MetricAggregation.SUM),
                    )
                },
            ),
            ("formula", {"formula": "a / b"}),
            ("interval", {"interval": "minute"}),
            (
                "group_by",
                {
                    "clauses": (
                        MetricQueryClause(
                            name="a",
                            metric_name="m1",
                            aggregation=MetricAggregation.SUM,
                            group_by=(MetricGroupBy(key="env"),),
                        ),
                    )
                },
            ),
            (
                "unsupported_aggregation",
                {"clauses": (MetricQueryClause(name="a", metric_name="m1", aggregation=MetricAggregation.RATE),)},
            ),
        ]
    )
    def test_not_yet_supported_features_raise_value_error(self, _name, overrides):
        with self.assertRaises(ValueError):
            run_metric_query(team=self.team, request=self._request(**overrides))


class TestMetricFilters(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        self.anchor = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="req",
            points=[(self.anchor - dt.timedelta(minutes=5), 1.0)],
            labels={"env": "prod", "path": "/api"},
            resource_labels={"k8s.pod.name": "web-1"},
        )
        seed_metric(
            team_id=self.team.id,
            metric_name="req",
            points=[(self.anchor - dt.timedelta(minutes=5), 10.0)],
            labels={"env": "dev", "path": "/web"},
            resource_labels={"k8s.pod.name": "web-2"},
        )

    def _total(self, filters: tuple[MetricFilter, ...]) -> float:
        runner = MetricQueryRunner(
            team=self.team,
            metric_name="req",
            aggregation="sum",
            date_from=self.anchor - dt.timedelta(hours=1),
            date_to=self.anchor,
            filters=filters,
        )
        return sum(row["value"] for row in runner.run())

    @parameterized.expand(
        [
            ("eq_attribute", MetricFilter(key="env", op=FilterOp.EQ, value="prod"), 1.0),
            ("neq_attribute", MetricFilter(key="env", op=FilterOp.NEQ, value="prod"), 10.0),
            ("regex", MetricFilter(key="path", op=FilterOp.REGEX, value="^/a"), 1.0),
            ("not_regex", MetricFilter(key="path", op=FilterOp.NOT_REGEX, value="^/a"), 10.0),
            (
                "eq_resource_scope",
                MetricFilter(key="k8s.pod.name", op=FilterOp.EQ, value="web-2", scope=AttributeScope.RESOURCE),
                10.0,
            ),
            (
                "auto_scope_falls_back_to_attribute",
                MetricFilter(key="env", op=FilterOp.EQ, value="dev", scope=AttributeScope.AUTO),
                10.0,
            ),
            ("eq_no_match", MetricFilter(key="env", op=FilterOp.EQ, value="staging"), 0.0),
            (
                "neq_matches_rows_lacking_key",
                MetricFilter(key="nonexistent", op=FilterOp.NEQ, value="x"),
                11.0,
            ),
        ]
    )
    def test_single_filter(self, _name, filter, expected_total):
        self.assertEqual(self._total((filter,)), expected_total)

    def test_filters_are_anded(self):
        self.assertEqual(
            self._total(
                (
                    MetricFilter(key="env", op=FilterOp.EQ, value="prod"),
                    MetricFilter(key="path", op=FilterOp.EQ, value="/api"),
                )
            ),
            1.0,
        )
        self.assertEqual(
            self._total(
                (
                    MetricFilter(key="env", op=FilterOp.EQ, value="prod"),
                    MetricFilter(key="path", op=FilterOp.EQ, value="/web"),
                )
            ),
            0.0,
        )

    def test_filters_via_api(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={
                "query": {
                    "metricName": "req",
                    "aggregation": "sum",
                    "filters": [{"key": "env", "op": "eq", "value": "prod"}],
                    "dateFrom": (self.anchor - dt.timedelta(hours=1)).isoformat(),
                    "dateTo": self.anchor.isoformat(),
                }
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        series = response.json()["results"][0]
        self.assertEqual(sum(p["value"] for p in series["points"]), 1.0)

    def test_filters_via_facade(self):
        series = run_metric_query(
            team=self.team,
            request=MetricQueryRequest(
                clauses=(
                    MetricQueryClause(
                        name="a",
                        metric_name="req",
                        aggregation=MetricAggregation.SUM,
                        filters=(MetricFilter(key="env", op=FilterOp.EQ, value="dev"),),
                    ),
                ),
                date_from=self.anchor - dt.timedelta(hours=1),
                date_to=self.anchor,
            ),
        )
        self.assertEqual(sum(p.value for p in series[0].points), 10.0)
