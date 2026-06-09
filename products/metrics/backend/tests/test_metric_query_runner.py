import json
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute

from products.metrics.backend.metric_query_runner import MetricQueryRunner, _pick_interval


def _insert_metric_row(
    *,
    team_id: int,
    metric_name: str,
    value: float,
    timestamp: dt.datetime,
    metric_type: str = "gauge",
) -> None:
    """Insert a single row into the local `metrics1` table.

    Uses the same shape `rust/capture-logs/src/metric_record.rs` emits, with
    fields the test doesn't care about set to empty/default.
    """
    row = {
        "uuid": "019e6bc4-4897-77d0-ab21-56ba3e2fe535",
        "team_id": team_id,
        "trace_id": "",
        "span_id": "",
        "trace_flags": 0,
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "observed_timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "service_name": "test-service",
        "metric_name": metric_name,
        "metric_type": metric_type,
        "value": value,
        "count": 1,
        "histogram_bounds": [],
        "histogram_counts": [],
        "unit": "",
        "aggregation_temporality": "cumulative",
        "is_monotonic": False,
        "resource_attributes": {},
        "instrumentation_scope": "",
        "attributes_map_str": {},
        "attributes_map_float": {},
    }
    sync_execute(f"INSERT INTO metrics1 FORMAT JSONEachRow {json.dumps(row)}")


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
        _insert_metric_row(
            team_id=self.team.id, metric_name="m1", value=2.0, timestamp=anchor - dt.timedelta(minutes=5)
        )
        _insert_metric_row(
            team_id=self.team.id, metric_name="m1", value=3.0, timestamp=anchor - dt.timedelta(minutes=5)
        )
        _insert_metric_row(
            team_id=self.team.id, metric_name="m1", value=4.0, timestamp=anchor - dt.timedelta(minutes=20)
        )
        # Different metric — should be filtered out.
        _insert_metric_row(
            team_id=self.team.id, metric_name="m2", value=99.0, timestamp=anchor - dt.timedelta(minutes=5)
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
        _insert_metric_row(team_id=99999, metric_name="m1", value=5.0, timestamp=anchor - dt.timedelta(minutes=5))

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
        _insert_metric_row(
            team_id=self.team.id, metric_name="m1", value=1.0, timestamp=anchor - dt.timedelta(minutes=10)
        )
        _insert_metric_row(
            team_id=self.team.id, metric_name="m1", value=2.0, timestamp=anchor - dt.timedelta(minutes=10)
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
        self.assertEqual(sum(point["value"] for point in body["results"]), 3.0)
