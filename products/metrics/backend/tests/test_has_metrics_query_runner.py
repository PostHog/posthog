import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.cache import cache

from rest_framework import status

from products.metrics.backend.has_metrics_query_runner import HasMetricsQueryRunner
from products.metrics.backend.tests._seeder import seed_metric, truncate_metrics_tables


def _insert_metric_row(*, team_id: int) -> None:
    seed_metric(
        team_id=team_id,
        metric_name="test.metric",
        points=[(dt.datetime(2026, 5, 27, tzinfo=dt.UTC), 1.0)],
    )


class TestHasMetricsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        cache.delete(f"team:{self.team.id}:has_metrics")

    def test_has_metrics_returns_false_when_no_metrics(self):
        truncate_metrics_tables()
        cache.delete(f"team:{self.team.id}:has_metrics")

        runner = HasMetricsQueryRunner(self.team)
        self.assertFalse(runner.run())

    def test_has_metrics_returns_true_when_metrics_exist(self):
        truncate_metrics_tables()
        cache.delete(f"team:{self.team.id}:has_metrics")
        _insert_metric_row(team_id=self.team.id)

        runner = HasMetricsQueryRunner(self.team)
        self.assertTrue(runner.run())

    def test_has_metrics_respects_team_isolation(self):
        truncate_metrics_tables()
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
        truncate_metrics_tables()
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

    def test_has_metrics_api_caches_negative_results_briefly(self):
        # Negatives are cached with a short TTL: the activation check reaches
        # this through the un-throttled add_product_intent request path, so an
        # uncached False is a per-request ClickHouse query. The TTL stays under
        # the setup prompt's 5s poll interval, so a team that just wired up
        # OTel still sees the flip within one extra poll cycle.
        cache.clear()

        with patch("products.metrics.backend.has_metrics_query_runner.HasMetricsQueryRunner") as mock_runner:
            mock_runner.return_value.run.return_value = False

            response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json(), {"hasMetrics": False})
            self.assertEqual(mock_runner.return_value.run.call_count, 1)

            # Second call within the TTL hits the cache, not ClickHouse
            response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json(), {"hasMetrics": False})
            self.assertEqual(mock_runner.return_value.run.call_count, 1)

    def test_has_metrics_negative_cache_expires(self):
        cache.clear()

        with (
            patch("products.metrics.backend.has_metrics_query_runner.HasMetricsQueryRunner") as mock_runner,
            patch("products.metrics.backend.has_metrics_query_runner.HAS_METRICS_NEGATIVE_CACHE_TTL", 0),
        ):
            mock_runner.return_value.run.return_value = False

            response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics")
            self.assertEqual(response.json(), {"hasMetrics": False})

            # TTL of 0 means the negative is not held: the next call re-queries
            response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics")
            self.assertEqual(response.json(), {"hasMetrics": False})
            self.assertEqual(mock_runner.return_value.run.call_count, 2)
