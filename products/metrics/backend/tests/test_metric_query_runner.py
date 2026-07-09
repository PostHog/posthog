import datetime as dt
from typing import Any

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

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
from products.metrics.backend.formula import evaluate, parse_formula
from products.metrics.backend.metric_query_runner import (
    MetricQueryRunner,
    _histogram_quantile,
    _pick_interval,
    attribute_field,
)
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

    def test_rejects_too_wide_date_range(self):
        now = timezone.now()
        with self.assertRaises(ValueError):
            MetricQueryRunner(
                team=self.team,
                metric_name="x",
                aggregation="sum",
                date_from=now - dt.timedelta(days=32),
                date_to=now,
            )

    def test_rejects_interval_exceeding_row_budget(self):
        now = timezone.now()
        with self.assertRaises(ValueError):
            MetricQueryRunner(
                team=self.team,
                metric_name="x",
                aggregation="sum",
                date_from=now - dt.timedelta(days=2),
                date_to=now,
                interval="second",
            )

    def test_rejects_invalid_regex_filter(self):
        now = timezone.now()
        runner = MetricQueryRunner(
            team=self.team,
            metric_name="x",
            aggregation="sum",
            date_from=now - dt.timedelta(hours=1),
            date_to=now,
            filters=(MetricFilter(key="container", op=FilterOp.REGEX, value="(["),),
        )
        with self.assertRaises(ValueError):
            runner.run()

    def test_raises_when_row_limit_truncates(self):
        anchor = timezone.now().replace(second=0, microsecond=0) - dt.timedelta(minutes=10)
        seed_metric(
            team_id=self.team.id,
            metric_name="m_trunc",
            points=[(anchor + dt.timedelta(minutes=m), 1.0) for m in range(6)],
        )
        runner = MetricQueryRunner(
            team=self.team,
            metric_name="m_trunc",
            aggregation="sum",
            date_from=anchor - dt.timedelta(minutes=1),
            date_to=anchor + dt.timedelta(minutes=10),
            interval="minute",
        )
        with patch("products.metrics.backend.metric_query_runner._ROW_LIMIT", 5):
            with self.assertRaises(ValueError):
                runner.run()

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

    def test_query_rejects_top_level_metric_type_with_clauses(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={
                "query": {
                    "clauses": [{"name": "a", "metricName": "m1", "aggregation": "sum"}],
                    "metricType": "gauge",
                    "dateFrom": "2026-01-01T00:00:00Z",
                }
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

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
            resource_labels={"service_version": "1.2.3"},
        )
        value = self._select_attribute(attribute_field("service_version", scope="resource"), "m_resource")
        self.assertEqual(value, "1.2.3")

    @parameterized.expand(
        [
            (f"{key}_{scope}", key, scope)
            for key in ("service_name", "service.name")
            for scope in ("auto", "resource", "attribute")
        ]
    )
    def test_service_name_resolves_to_first_class_column(self, _name: str, key: str, scope: str) -> None:
        # Real ingestion extracts the service name into its own column (the
        # maps carry the dotted `service.name` at best), so both spellings
        # must read the column in every scope.
        anchor = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="m_service",
            points=[(anchor, 1.0)],
            service_name="logs-ingestion",
        )
        value = self._select_attribute(attribute_field(key, scope=scope), "m_service")  # type: ignore[arg-type]
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
                "unsupported_aggregation",
                {"clauses": (MetricQueryClause(name="a", metric_name="m1", aggregation=MetricAggregation.MIN),)},
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


class TestGroupBy(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        self.anchor = timezone.now().replace(microsecond=0, second=0)
        # env=prod has points in two buckets, env=dev only in the second —
        # exercises the shared-grid zero-fill.
        seed_metric(
            team_id=self.team.id,
            metric_name="req",
            points=[(self.anchor - dt.timedelta(minutes=10), 1.0), (self.anchor - dt.timedelta(minutes=5), 2.0)],
            labels={"env": "prod"},
        )
        seed_metric(
            team_id=self.team.id,
            metric_name="req",
            points=[(self.anchor - dt.timedelta(minutes=5), 10.0)],
            labels={"env": "dev"},
        )

    def _run(self, **request_overrides):
        defaults: dict[str, Any] = {
            "clauses": (
                MetricQueryClause(
                    name="a",
                    metric_name="req",
                    aggregation=MetricAggregation.SUM,
                    group_by=(MetricGroupBy(key="env"),),
                ),
            ),
            "date_from": self.anchor - dt.timedelta(hours=1),
            "date_to": self.anchor,
        }
        defaults.update(request_overrides)
        return run_metric_query(team=self.team, request=MetricQueryRequest(**defaults))

    def test_one_series_per_group_with_shared_zero_filled_grid(self):
        series = self._run()

        self.assertEqual(len(series), 2)
        by_env = {s.labels["env"]: s for s in series}
        self.assertEqual(set(by_env), {"prod", "dev"})

        prod_times = [p.time for p in by_env["prod"].points]
        dev_times = [p.time for p in by_env["dev"].points]
        self.assertEqual(prod_times, dev_times)

        self.assertEqual(sum(p.value for p in by_env["prod"].points), 3.0)
        self.assertEqual(sum(p.value for p in by_env["dev"].points), 10.0)
        # dev has no data in prod's first bucket: zero-filled, not missing.
        self.assertIn(0.0, [p.value for p in by_env["dev"].points])

    def test_series_ordered_largest_first(self):
        series = self._run()
        self.assertEqual(series[0].labels["env"], "dev")

    def test_explicit_interval_respected(self):
        series = self._run(interval="minute_5")
        # 10-minute spread at 5m buckets: both points land in distinct buckets
        by_env = {s.labels["env"]: s for s in series}
        self.assertEqual(len(by_env["prod"].points), len(by_env["dev"].points))

    def test_unknown_interval_raises(self):
        with self.assertRaises(ValueError):
            self._run(interval="fortnight")

    def test_group_by_resource_scope(self):
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        seed_metric(
            team_id=self.team.id,
            metric_name="req",
            points=[(self.anchor - dt.timedelta(minutes=5), 7.0)],
            resource_labels={"k8s.pod.name": "web-1"},
        )
        series = self._run(
            clauses=(
                MetricQueryClause(
                    name="a",
                    metric_name="req",
                    aggregation=MetricAggregation.SUM,
                    group_by=(MetricGroupBy(key="k8s.pod.name", scope=AttributeScope.RESOURCE),),
                ),
            )
        )
        self.assertEqual(series[0].labels, {"k8s.pod.name": "web-1"})

    def test_group_by_via_api(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={
                "query": {
                    "metricName": "req",
                    "aggregation": "sum",
                    "groupBy": [{"key": "env"}],
                    "interval": "minute",
                    "dateFrom": (self.anchor - dt.timedelta(hours=1)).isoformat(),
                    "dateTo": self.anchor.isoformat(),
                }
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual({s["labels"]["env"] for s in results}, {"prod", "dev"})

    def test_series_cap_keeps_largest(self):
        with patch("products.metrics.backend.facade.api.MAX_SERIES_PER_CLAUSE", 1):
            series = self._run()
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0].labels["env"], "dev")


class TestRateIncrease(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        # Anchor on a minute boundary so bucket membership is deterministic.
        self.anchor = (timezone.now() - dt.timedelta(minutes=30)).replace(second=0, microsecond=0)

    def _run(self, aggregation: str, **runner_overrides):
        defaults: dict[str, Any] = {
            "team": self.team,
            "metric_name": "requests_total",
            "aggregation": aggregation,
            "date_from": self.anchor - dt.timedelta(minutes=1),
            "date_to": self.anchor + dt.timedelta(minutes=2),
            "interval": "minute",
        }
        defaults.update(runner_overrides)
        return MetricQueryRunner(**defaults).run()

    def _seed_counter(self, points, **kwargs):
        seed_metric(
            team_id=self.team.id,
            metric_name="requests_total",
            metric_type="sum",
            is_monotonic=True,
            points=points,
            **kwargs,
        )

    def test_increase_diffs_cumulative_samples_and_ignores_first(self):
        self._seed_counter(
            [
                (self.anchor + dt.timedelta(seconds=0), 100.0),
                (self.anchor + dt.timedelta(seconds=15), 105.0),
                (self.anchor + dt.timedelta(seconds=30), 110.0),
                (self.anchor + dt.timedelta(seconds=45), 115.0),
                (self.anchor + dt.timedelta(seconds=60), 120.0),
                (self.anchor + dt.timedelta(seconds=75), 125.0),
            ]
        )
        rows = self._run("increase")
        by_time = {row["time"]: row["value"] for row in rows}
        values = list(by_time.values())
        # bucket 1: first sample contributes 0, then 5+5+5; bucket 2: 5+5
        self.assertEqual(values, [15.0, 10.0])

    def test_rate_divides_by_bucket_seconds(self):
        self._seed_counter(
            [
                (self.anchor + dt.timedelta(seconds=0), 0.0),
                (self.anchor + dt.timedelta(seconds=30), 30.0),
            ]
        )
        rows = self._run("rate")
        self.assertEqual([row["value"] for row in rows], [0.5])

    def test_counter_reset_counts_post_reset_value(self):
        self._seed_counter(
            [
                (self.anchor + dt.timedelta(seconds=0), 10.0),
                (self.anchor + dt.timedelta(seconds=15), 20.0),
                (self.anchor + dt.timedelta(seconds=30), 5.0),
                (self.anchor + dt.timedelta(seconds=45), 15.0),
            ]
        )
        rows = self._run("increase")
        # 0 (first) + 10 + 5 (reset: post-reset absolute value) + 10
        self.assertEqual([row["value"] for row in rows], [25.0])

    def test_delta_temporality_sums_samples_directly(self):
        self._seed_counter(
            [
                (self.anchor + dt.timedelta(seconds=0), 3.0),
                (self.anchor + dt.timedelta(seconds=15), 4.0),
                (self.anchor + dt.timedelta(seconds=30), 5.0),
            ],
            aggregation_temporality="delta",
        )
        rows = self._run("increase")
        self.assertEqual([row["value"] for row in rows], [12.0])

    def test_deltas_are_computed_per_underlying_series(self):
        # Two pods with interleaved timestamps; naive global diffing would
        # produce garbage from the cross-series jumps.
        self._seed_counter(
            [
                (self.anchor + dt.timedelta(seconds=0), 1000.0),
                (self.anchor + dt.timedelta(seconds=30), 1010.0),
            ],
            resource_labels={"k8s.pod.name": "web-1"},
        )
        self._seed_counter(
            [
                (self.anchor + dt.timedelta(seconds=15), 5.0),
                (self.anchor + dt.timedelta(seconds=45), 10.0),
            ],
            resource_labels={"k8s.pod.name": "web-2"},
        )
        rows = self._run("increase")
        self.assertEqual([row["value"] for row in rows], [15.0])

    def test_rate_composes_with_group_by(self):
        self._seed_counter(
            [
                (self.anchor + dt.timedelta(seconds=0), 0.0),
                (self.anchor + dt.timedelta(seconds=30), 60.0),
            ],
            resource_labels={"k8s.pod.name": "web-1"},
        )
        self._seed_counter(
            [
                (self.anchor + dt.timedelta(seconds=0), 0.0),
                (self.anchor + dt.timedelta(seconds=30), 6.0),
            ],
            resource_labels={"k8s.pod.name": "web-2"},
        )
        rows = self._run(
            "increase",
            group_by=(MetricGroupBy(key="k8s.pod.name", scope=AttributeScope.RESOURCE),),
        )
        by_pod = {row["labels"]["k8s.pod.name"]: row["value"] for row in rows}
        self.assertEqual(by_pod, {"web-1": 60.0, "web-2": 6.0})

    def test_rate_via_facade_and_api(self):
        self._seed_counter(
            [
                (self.anchor + dt.timedelta(seconds=0), 0.0),
                (self.anchor + dt.timedelta(seconds=30), 30.0),
            ]
        )
        series = run_metric_query(
            team=self.team,
            request=MetricQueryRequest(
                clauses=(
                    MetricQueryClause(name="a", metric_name="requests_total", aggregation=MetricAggregation.RATE),
                ),
                date_from=self.anchor - dt.timedelta(minutes=1),
                date_to=self.anchor + dt.timedelta(minutes=2),
                interval="minute",
            ),
        )
        self.assertEqual([p.value for p in series[0].points], [0.5])

        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={
                "query": {
                    "metricName": "requests_total",
                    "aggregation": "increase",
                    "interval": "minute",
                    "dateFrom": (self.anchor - dt.timedelta(minutes=1)).isoformat(),
                    "dateTo": (self.anchor + dt.timedelta(minutes=2)).isoformat(),
                }
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [p["value"] for p in response.json()["results"][0]["points"]],
            [30.0],
        )


class TestHistogramQuantileInterpolation:
    @parameterized.expand(
        [
            # bounds [0.1, 0.5, 1.0], counts [10, 10, 10, 0] (no overflow):
            # p50 -> rank 15, second bucket [0.1, 0.5], 5/10 through -> 0.3
            ("p50_mid_bucket", 0.5, [0.1, 0.5, 1.0], [10.0, 10.0, 10.0, 0.0], 0.3),
            # p25 -> rank 7.5, first bucket [0, 0.1], 7.5/10 through -> 0.075
            ("p25_first_bucket", 0.25, [0.1, 0.5, 1.0], [10.0, 10.0, 10.0, 0.0], 0.075),
            # rank lands in the overflow bucket -> clamp to highest bound
            ("overflow_clamps", 0.99, [0.1, 0.5, 1.0], [1.0, 1.0, 1.0, 10.0], 1.0),
            ("empty_counts", 0.5, [0.1, 0.5], [0.0, 0.0, 0.0], 0.0),
            ("no_bounds", 0.5, [], [10.0], 0.0),
        ]
    )
    def test_interpolation(self, _name, q, bounds, counts, expected):
        assert abs(_histogram_quantile(q, bounds, counts) - expected) < 1e-9


class TestHistogramQuantileRunner(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    BOUNDS = [0.1, 0.5, 1.0]

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        self.anchor = (timezone.now() - dt.timedelta(minutes=30)).replace(second=0, microsecond=0)

    def _seed_histogram(self, points_with_counts, temporality="cumulative", bounds=None, **kwargs):
        for timestamp, counts in points_with_counts:
            seed_metric(
                team_id=self.team.id,
                metric_name="latency",
                metric_type="histogram",
                aggregation_temporality=temporality,
                histogram_bounds=bounds or self.BOUNDS,
                histogram_counts=counts,
                points=[(timestamp, 0.0)],
                **kwargs,
            )

    def _run(self, quantile=0.5, **overrides):
        defaults: dict[str, Any] = {
            "team": self.team,
            "metric_name": "latency",
            "aggregation": "histogram_quantile",
            "quantile": quantile,
            "date_from": self.anchor - dt.timedelta(minutes=1),
            "date_to": self.anchor + dt.timedelta(minutes=2),
            "interval": "minute",
        }
        defaults.update(overrides)
        return MetricQueryRunner(**defaults).run()

    def test_requires_quantile(self):
        with self.assertRaises(ValueError):
            self._run(quantile=None)
        with self.assertRaises(ValueError):
            self._run(quantile=1.5)

    def test_group_by_service_name_column(self):
        # service_name resolves to the raw column, which the nested
        # per-series subqueries must propagate to the outer group-by.
        self._seed_histogram([(self.anchor, [10, 0, 0, 0])], temporality="delta", service_name="svc-a")
        self._seed_histogram([(self.anchor, [0, 0, 10, 0])], temporality="delta", service_name="svc-b")
        rows = self._run(group_by=(MetricGroupBy(key="service_name"),))
        self.assertEqual(sorted(row["labels"]["service_name"] for row in rows), ["svc-a", "svc-b"])

    def test_delta_histogram_p50(self):
        self._seed_histogram(
            [
                (self.anchor + dt.timedelta(seconds=0), [10, 10, 10, 0]),
                (self.anchor + dt.timedelta(seconds=30), [10, 10, 10, 0]),
            ],
            temporality="delta",
        )
        rows = self._run(0.5)
        # combined counts [20, 20, 20, 0]: rank 30, mid of second bucket
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["value"], 0.3)

    def test_cumulative_histogram_diffs_per_series(self):
        # Cumulative counts grow; first sample contributes nothing.
        self._seed_histogram(
            [
                (self.anchor + dt.timedelta(seconds=0), [100, 100, 100, 0]),
                (self.anchor + dt.timedelta(seconds=30), [110, 110, 110, 0]),
            ],
            temporality="cumulative",
        )
        rows = self._run(0.5)
        # window contribution [10, 10, 10, 0] -> p50 = 0.3
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["value"], 0.3)

    def test_cumulative_lone_sample_emits_no_point(self):
        # A cumulative histogram's first (and only) sample has no predecessor
        # to diff against — the window has no computable increase. That must
        # be a gap, not a fabricated p95 of 0 (which reads as "p95 is 0s").
        self._seed_histogram([(self.anchor, [1, 1, 1, 0])], temporality="cumulative")
        rows = self._run(0.95)
        self.assertEqual(rows, [])

    def test_mismatched_bounds_raise(self):
        self._seed_histogram([(self.anchor + dt.timedelta(seconds=0), [1, 1, 1, 0])], temporality="delta")
        self._seed_histogram(
            [(self.anchor + dt.timedelta(seconds=10), [1, 1, 1, 0])],
            temporality="delta",
            bounds=[0.2, 0.6, 2.0],
            resource_labels={"k8s.pod.name": "other"},
        )
        with self.assertRaises(ValueError):
            self._run(0.5)

    def test_histogram_quantile_via_api(self):
        self._seed_histogram(
            [(self.anchor + dt.timedelta(seconds=0), [10, 10, 10, 0])],
            temporality="delta",
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={
                "query": {
                    "metricName": "latency",
                    "aggregation": "histogram_quantile",
                    "quantile": 0.5,
                    "interval": "minute",
                    "dateFrom": (self.anchor - dt.timedelta(minutes=1)).isoformat(),
                    "dateTo": (self.anchor + dt.timedelta(minutes=2)).isoformat(),
                }
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        points = response.json()["results"][0]["points"]
        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(points[0]["value"], 0.3)

    def test_histogram_quantile_via_api_requires_quantile(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={
                "query": {
                    "metricName": "latency",
                    "aggregation": "histogram_quantile",
                    "dateFrom": (self.anchor - dt.timedelta(minutes=1)).isoformat(),
                }
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestFormulaParser:
    @parameterized.expand(
        [
            ("add", "a + b", {"a": 3.0, "b": 4.0}, 7.0),
            ("precedence", "a + b * 2", {"a": 1.0, "b": 2.0}, 5.0),
            ("parens", "(a - b) / a", {"a": 10.0, "b": 4.0}, 0.6),
            ("unary_minus", "-a + 5", {"a": 2.0}, 3.0),
            ("division_by_zero_yields_zero", "a / b", {"a": 5.0, "b": 0.0}, 0.0),
            ("number_only_arithmetic", "a * 0 + 1.5", {"a": 9.0}, 1.5),
        ]
    )
    def test_evaluate(self, _name, formula, values, expected):
        node = parse_formula(formula, frozenset(values))
        assert abs(evaluate(node, values) - expected) < 1e-9

    @parameterized.expand(
        [
            ("unknown_clause", "a + zz", frozenset({"a", "b"})),
            ("unbalanced_parens", "(a + b", frozenset({"a", "b"})),
            ("trailing_garbage", "a + b )", frozenset({"a", "b"})),
            ("empty", "   ", frozenset({"a"})),
            ("bad_char", "a ^ b", frozenset({"a", "b"})),
            ("nesting_too_deep_parens", "(" * 40 + "a" + ")" * 40, frozenset({"a"})),
            ("nesting_too_deep_unary", "-" * 40 + "a", frozenset({"a"})),
        ]
    )
    def test_rejects(self, _name, formula, names):
        with pytest.raises(ValueError):
            parse_formula(formula, names)


class TestMultiClauseAndFormulas(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        self.anchor = (timezone.now() - dt.timedelta(minutes=30)).replace(second=0, microsecond=0)
        # errors: 2 then 4; requests: 10 then 20 (per-minute buckets)
        seed_metric(
            team_id=self.team.id,
            metric_name="errors",
            points=[(self.anchor + dt.timedelta(seconds=10), 2.0), (self.anchor + dt.timedelta(seconds=70), 4.0)],
        )
        seed_metric(
            team_id=self.team.id,
            metric_name="requests",
            points=[(self.anchor + dt.timedelta(seconds=10), 10.0), (self.anchor + dt.timedelta(seconds=70), 20.0)],
        )

    def _request(self, formula=None, clauses=None):
        return MetricQueryRequest(
            clauses=clauses
            or (
                MetricQueryClause(name="a", metric_name="errors", aggregation=MetricAggregation.SUM),
                MetricQueryClause(name="b", metric_name="requests", aggregation=MetricAggregation.SUM),
            ),
            date_from=self.anchor - dt.timedelta(minutes=1),
            date_to=self.anchor + dt.timedelta(minutes=2),
            interval="minute",
            formula=formula,
        )

    def test_multi_clause_returns_all_series_on_shared_grid(self):
        series = run_metric_query(team=self.team, request=self._request())
        self.assertEqual(len(series), 2)
        by_clause = {s.clause: s for s in series}
        self.assertEqual([p.value for p in by_clause["a"].points], [2.0, 4.0])
        self.assertEqual([p.value for p in by_clause["b"].points], [10.0, 20.0])
        self.assertEqual(
            [p.time for p in by_clause["a"].points],
            [p.time for p in by_clause["b"].points],
        )

    def test_formula_error_rate(self):
        series = run_metric_query(team=self.team, request=self._request(formula="a / b"))
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0].clause, "formula")
        self.assertIsNone(series[0].metric_name)
        self.assertEqual([p.value for p in series[0].points], [0.2, 0.2])

    def test_formula_matches_grouped_series_by_label_set(self):
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        for env, errors, requests in [("prod", 1.0, 10.0), ("dev", 3.0, 6.0)]:
            seed_metric(
                team_id=self.team.id,
                metric_name="errors",
                points=[(self.anchor + dt.timedelta(seconds=10), errors)],
                labels={"env": env},
            )
            seed_metric(
                team_id=self.team.id,
                metric_name="requests",
                points=[(self.anchor + dt.timedelta(seconds=10), requests)],
                labels={"env": env},
            )
        group = (MetricGroupBy(key="env"),)
        series = run_metric_query(
            team=self.team,
            request=self._request(
                formula="a / b",
                clauses=(
                    MetricQueryClause(
                        name="a", metric_name="errors", aggregation=MetricAggregation.SUM, group_by=group
                    ),
                    MetricQueryClause(
                        name="b", metric_name="requests", aggregation=MetricAggregation.SUM, group_by=group
                    ),
                ),
            ),
        )
        by_env = {s.labels["env"]: [p.value for p in s.points] for s in series}
        self.assertEqual(by_env, {"prod": [0.1], "dev": [0.5]})

    def test_formula_broadcasts_ungrouped_clause(self):
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        for env, errors in [("prod", 2.0), ("dev", 6.0)]:
            seed_metric(
                team_id=self.team.id,
                metric_name="errors",
                points=[(self.anchor + dt.timedelta(seconds=10), errors)],
                labels={"env": env},
            )
        seed_metric(
            team_id=self.team.id,
            metric_name="requests",
            points=[(self.anchor + dt.timedelta(seconds=10), 20.0)],
        )
        series = run_metric_query(
            team=self.team,
            request=self._request(
                formula="a / b",
                clauses=(
                    MetricQueryClause(
                        name="a",
                        metric_name="errors",
                        aggregation=MetricAggregation.SUM,
                        group_by=(MetricGroupBy(key="env"),),
                    ),
                    MetricQueryClause(name="b", metric_name="requests", aggregation=MetricAggregation.SUM),
                ),
            ),
        )
        by_env = {s.labels["env"]: [p.value for p in s.points] for s in series}
        self.assertEqual(by_env, {"prod": [0.1], "dev": [0.3]})

    def test_unknown_clause_in_formula_raises(self):
        with self.assertRaises(ValueError):
            run_metric_query(team=self.team, request=self._request(formula="a / zz"))

    def test_clauses_and_formula_via_api(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={
                "query": {
                    "clauses": [
                        {"name": "a", "metricName": "errors", "aggregation": "sum"},
                        {"name": "b", "metricName": "requests", "aggregation": "sum"},
                    ],
                    "formula": "(b - a) / b",
                    "interval": "minute",
                    "dateFrom": (self.anchor - dt.timedelta(minutes=1)).isoformat(),
                    "dateTo": (self.anchor + dt.timedelta(minutes=2)).isoformat(),
                }
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        series = response.json()["results"][0]
        self.assertEqual(series["clause"], "formula")
        self.assertEqual([p["value"] for p in series["points"]], [0.8, 0.8])

    def test_api_rejects_both_shorthand_and_clauses(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={
                "query": {
                    "metricName": "errors",
                    "clauses": [{"name": "a", "metricName": "errors"}],
                    "dateFrom": (self.anchor - dt.timedelta(minutes=1)).isoformat(),
                }
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestMetricTypeIsolation(ClickhouseTestMixin, APIBaseTest):
    """One metric name existing as several types (e.g. a counter and a gauge)
    must not blend into one aggregate — series identity includes the type."""

    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        self.anchor = (timezone.now() - dt.timedelta(minutes=30)).replace(second=0, microsecond=0)
        # The same name recorded as a delta counter (5) and as a gauge (42).
        seed_metric(
            team_id=self.team.id,
            metric_name="m_collide",
            points=[(self.anchor, 5.0)],
            metric_type="sum",
            aggregation_temporality="delta",
            is_monotonic=True,
        )
        seed_metric(
            team_id=self.team.id,
            metric_name="m_collide",
            points=[(self.anchor, 42.0)],
            metric_type="gauge",
        )

    def _run(self, aggregation: str, metric_type: str | None, **kwargs: Any) -> list[dict[str, Any]]:
        return MetricQueryRunner(
            team=self.team,
            metric_name="m_collide",
            aggregation=aggregation,
            date_from=self.anchor - dt.timedelta(minutes=5),
            date_to=self.anchor + dt.timedelta(minutes=5),
            metric_type=metric_type,
            **kwargs,
        ).run()

    @parameterized.expand(
        [
            # Without isolation these blended: avg was (5 + 42) / 2 = 23.5.
            ("gauge_avg", "avg", "gauge", 42.0),
            ("counter_sum", "sum", "sum", 5.0),
            ("counter_increase", "increase", "sum", 5.0),
        ]
    )
    def test_type_filter_isolates_series(self, _name: str, aggregation: str, metric_type: str, expected: float):
        rows = self._run(aggregation, metric_type)
        assert [row["value"] for row in rows] == [expected]

    def test_without_type_filter_all_rows_still_match(self):
        # Back-compat: no metric_type keeps the pre-filter behavior.
        rows = self._run("count", None)
        assert [row["value"] for row in rows] == [2]

    def test_rejects_unknown_metric_type(self):
        with self.assertRaises(ValueError):
            self._run("avg", "flurble")

    def test_histogram_quantile_ignores_same_named_non_histogram_rows(self):
        seed_metric(
            team_id=self.team.id,
            metric_name="m_collide",
            points=[(self.anchor, 30.0)],
            metric_type="histogram",
            aggregation_temporality="delta",
            histogram_bounds=[10.0, 50.0, 100.0],
            histogram_counts=[0, 10, 0, 0],
        )
        # No explicit type needed: the histogram path must constrain itself.
        rows = self._run("histogram_quantile", None, quantile=0.5)
        assert len(rows) == 1
        # All 10 observations sit in the (10, 50] bucket; p50 interpolates to 30.
        assert abs(rows[0]["value"] - 30.0) < 1e-9

    def test_api_accepts_metric_type(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={
                "query": {
                    "metricName": "m_collide",
                    "aggregation": "avg",
                    "metricType": "gauge",
                    "dateFrom": (self.anchor - dt.timedelta(minutes=5)).isoformat(),
                    "dateTo": (self.anchor + dt.timedelta(minutes=5)).isoformat(),
                }
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        series = response.json()["results"][0]
        self.assertEqual([p["value"] for p in series["points"]], [42.0])


class TestNonFiniteAggregates(ClickhouseTestMixin, APIBaseTest):
    """ClickHouse float aggregates can overflow to inf (two 1e308 samples in
    one bucket). A Python `inf` leaking into the response is at best invalid
    JSON ("Infinity") and at worst a silent null downstream — the API contract
    is an explicit null gap instead."""

    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        self.anchor = (timezone.now() - dt.timedelta(minutes=30)).replace(second=0, microsecond=0)

    def _seed_huge(self, count: int) -> None:
        seed_metric(
            team_id=self.team.id,
            metric_name="m_huge",
            points=[(self.anchor + dt.timedelta(seconds=i), 1e308) for i in range(count)],
        )

    def _run(self, aggregation: str) -> list[dict[str, Any]]:
        return MetricQueryRunner(
            team=self.team,
            metric_name="m_huge",
            aggregation=aggregation,
            date_from=self.anchor - dt.timedelta(minutes=5),
            date_to=self.anchor + dt.timedelta(minutes=5),
        ).run()

    @parameterized.expand([("sum",), ("avg",)])
    def test_overflowing_bucket_returns_null_gap(self, aggregation: str):
        self._seed_huge(2)
        rows = self._run(aggregation)
        assert [row["value"] for row in rows] == [None]

    def test_large_finite_value_survives(self):
        self._seed_huge(1)
        rows = self._run("avg")
        assert [row["value"] for row in rows] == [1e308]

    def test_overflow_serializes_as_json_null_via_api(self):
        self._seed_huge(2)
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={
                "query": {
                    "metricName": "m_huge",
                    "aggregation": "sum",
                    "dateFrom": (self.anchor - dt.timedelta(minutes=5)).isoformat(),
                    "dateTo": (self.anchor + dt.timedelta(minutes=5)).isoformat(),
                }
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        values = [p["value"] for p in response.json()["results"][0]["points"]]
        assert values == [None]

    def test_formula_overflow_returns_null_gap(self):
        self._seed_huge(1)
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={
                "query": {
                    "clauses": [{"name": "a", "metricName": "m_huge", "aggregation": "avg"}],
                    "formula": "a * a",
                    "dateFrom": (self.anchor - dt.timedelta(minutes=5)).isoformat(),
                    "dateTo": (self.anchor + dt.timedelta(minutes=5)).isoformat(),
                }
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        values = [p["value"] for p in response.json()["results"][0]["points"]]
        assert values == [None]

    def test_formula_propagates_clause_null_gap(self):
        # Two 1e308 points sum to inf, so the CLAUSE aggregate is already a
        # null gap before the formula runs — exercising the input-None guard
        # in _evaluate_formula_point, not the formula-overflow branch above.
        self._seed_huge(2)
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/query",
            data={
                "query": {
                    "clauses": [{"name": "a", "metricName": "m_huge", "aggregation": "sum"}],
                    "formula": "a + 1",
                    "dateFrom": (self.anchor - dt.timedelta(minutes=5)).isoformat(),
                    "dateTo": (self.anchor + dt.timedelta(minutes=5)).isoformat(),
                }
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        values = [p["value"] for p in response.json()["results"][0]["points"]]
        assert values == [None]
