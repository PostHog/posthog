import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.cache import cache

from rest_framework import status

from posthog.clickhouse.client import sync_execute

from products.metrics.backend.has_metrics_query_runner import HasMetricsQueryRunner


def _insert_metric_row(*, team_id: int) -> None:
    """Insert a minimal row into the local `metrics1` storage table.

    `metrics` is a Distributed proxy over `metrics1`; INSERTs forward
    through Distributed but TRUNCATEs must hit the local table directly
    (Distributed doesn't support TRUNCATE).
    """
    row = {
        "uuid": "019e6bc4-4897-77d0-ab21-56ba3e2fe535",
        "team_id": team_id,
        "trace_id": "",
        "span_id": "",
        "trace_flags": 0,
        "timestamp": "2026-05-27 00:00:00.000000",
        "observed_timestamp": "2026-05-27 00:00:00.000000",
        "service_name": "test-service",
        "metric_name": "test.metric",
        "metric_type": "gauge",
        "value": 1.0,
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


class TestHasMetricsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        cache.delete(f"team:{self.team.id}:has_metrics")

    def test_has_metrics_returns_false_when_no_metrics(self):
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        cache.delete(f"team:{self.team.id}:has_metrics")

        runner = HasMetricsQueryRunner(self.team)
        self.assertFalse(runner.run())

    def test_has_metrics_returns_true_when_metrics_exist(self):
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        cache.delete(f"team:{self.team.id}:has_metrics")
        _insert_metric_row(team_id=self.team.id)

        runner = HasMetricsQueryRunner(self.team)
        self.assertTrue(runner.run())

    def test_has_metrics_respects_team_isolation(self):
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        cache.delete(f"team:{self.team.id}:has_metrics")
        # Row belongs to a different team — the HogQL team_id auto-filter
        # should make our team's runner return False.
        _insert_metric_row(team_id=99999)

        runner = HasMetricsQueryRunner(self.team)
        self.assertFalse(runner.run())


class TestHasMetricsAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        cache.delete(f"team:{self.team.id}:has_metrics")

    def test_has_metrics_api_returns_false_when_no_metrics(self):
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        cache.delete(f"team:{self.team.id}:has_metrics")

        response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"hasMetrics": False})

    def test_has_metrics_api_requires_authentication(self):
        self.client.logout()
        response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_has_metrics_api_caches_positive_results(self):
        cache.clear()

        with (
            patch("products.metrics.backend.has_metrics_query_runner.HasMetricsQueryRunner") as mock_runner,
            patch("products.metrics.backend.presentation.api.report_user_action") as mock_report,
        ):
            mock_runner.return_value.run.return_value = True

            response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json(), {"hasMetrics": True})
            self.assertEqual(mock_runner.return_value.run.call_count, 1)

            assert mock_report.call_args[0][1] == "metrics has_metrics checked"
            assert mock_report.call_args[0][2]["has_metrics"] is True

            # Second call hits the cache, not the runner
            response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json(), {"hasMetrics": True})
            self.assertEqual(mock_runner.return_value.run.call_count, 1)

            assert mock_report.call_count == 2

    def test_has_metrics_api_does_not_cache_negative_results(self):
        cache.clear()

        with patch("products.metrics.backend.has_metrics_query_runner.HasMetricsQueryRunner") as mock_runner:
            mock_runner.return_value.run.return_value = False

            response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json(), {"hasMetrics": False})
            self.assertEqual(mock_runner.return_value.run.call_count, 1)

            response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json(), {"hasMetrics": False})
            self.assertEqual(mock_runner.return_value.run.call_count, 2)
