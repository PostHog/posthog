import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from rest_framework import status

from posthog.clickhouse.client import sync_execute

from products.metrics.backend.metric_names_query_runner import MetricNamesQueryRunner
from products.metrics.backend.tests._seeder import seed_metric


def _seed_point(
    *,
    team_id: int,
    metric_name: str,
    value: float,
    timestamp: dt.datetime,
    metric_type: str = "gauge",
) -> None:
    seed_metric(team_id=team_id, metric_name=metric_name, points=[(timestamp, value)], metric_type=metric_type)


class TestMetricNamesQueryRunner(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")

    def test_rejects_out_of_range_limit(self):
        with self.assertRaises(ValueError):
            MetricNamesQueryRunner(team=self.team, limit=0)
        with self.assertRaises(ValueError):
            MetricNamesQueryRunner(team=self.team, limit=10_000)

    def test_rejects_non_positive_lookback(self):
        with self.assertRaises(ValueError):
            MetricNamesQueryRunner(team=self.team, lookback=dt.timedelta(0))

    def test_returns_empty_for_no_data(self):
        runner = MetricNamesQueryRunner(team=self.team)
        self.assertEqual(runner.run(), [])

    def test_returns_distinct_names_with_metric_type(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        _seed_point(
            team_id=self.team.id,
            metric_name="http.server.duration",
            value=1.0,
            timestamp=anchor,
            metric_type="histogram",
        )
        _seed_point(
            team_id=self.team.id,
            metric_name="http.server.duration",
            value=2.0,
            timestamp=anchor,
            metric_type="histogram",
        )
        _seed_point(
            team_id=self.team.id,
            metric_name="queue.depth",
            value=12.0,
            timestamp=anchor,
            metric_type="gauge",
        )

        runner = MetricNamesQueryRunner(team=self.team)
        results = runner.run()

        names = {row["name"] for row in results}
        self.assertEqual(names, {"http.server.duration", "queue.depth"})

        by_name = {row["name"]: row["metric_type"] for row in results}
        self.assertEqual(by_name["http.server.duration"], "histogram")
        self.assertEqual(by_name["queue.depth"], "gauge")

    def test_search_filters_by_substring(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        _seed_point(team_id=self.team.id, metric_name="http.server.duration", value=1.0, timestamp=anchor)
        _seed_point(team_id=self.team.id, metric_name="queue.depth", value=12.0, timestamp=anchor)

        runner = MetricNamesQueryRunner(team=self.team, search="server")
        results = runner.run()
        self.assertEqual([row["name"] for row in results], ["http.server.duration"])

    def test_exact_match_floats_to_top(self):
        anchor = timezone.now().replace(microsecond=0)
        _seed_point(
            team_id=self.team.id,
            metric_name="foo.bar",
            value=1.0,
            timestamp=anchor - dt.timedelta(minutes=10),
        )
        _seed_point(
            team_id=self.team.id,
            metric_name="bar",
            value=2.0,
            timestamp=anchor - dt.timedelta(minutes=1),
        )

        runner = MetricNamesQueryRunner(team=self.team, search="bar")
        results = runner.run()
        self.assertEqual(results[0]["name"], "bar")

    def test_respects_team_isolation(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        _seed_point(team_id=99999, metric_name="other.team.metric", value=1.0, timestamp=anchor)

        runner = MetricNamesQueryRunner(team=self.team)
        self.assertEqual(runner.run(), [])

    def test_lookback_excludes_old_data(self):
        old = timezone.now().replace(microsecond=0) - dt.timedelta(days=14)
        recent = timezone.now().replace(microsecond=0) - dt.timedelta(hours=1)
        _seed_point(team_id=self.team.id, metric_name="old.metric", value=1.0, timestamp=old)
        _seed_point(team_id=self.team.id, metric_name="recent.metric", value=2.0, timestamp=recent)

        runner = MetricNamesQueryRunner(team=self.team, lookback=dt.timedelta(days=7))
        names = [row["name"] for row in runner.run()]
        self.assertIn("recent.metric", names)
        self.assertNotIn("old.metric", names)


class TestMetricsValuesAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")

    def test_values_requires_authentication(self):
        self.client.logout()
        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_values_returns_empty_for_no_data(self):
        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"results": []})

    def test_values_returns_metric_names(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        _seed_point(team_id=self.team.id, metric_name="m1", value=1.0, timestamp=anchor)
        _seed_point(team_id=self.team.id, metric_name="m2", value=2.0, timestamp=anchor, metric_type="gauge")

        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        names = {row["name"] for row in body["results"]}
        self.assertEqual(names, {"m1", "m2"})

    def test_values_search_param(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        _seed_point(team_id=self.team.id, metric_name="http.duration", value=1.0, timestamp=anchor)
        _seed_point(team_id=self.team.id, metric_name="queue.depth", value=2.0, timestamp=anchor)

        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values?value=http")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in response.json()["results"]]
        self.assertEqual(names, ["http.duration"])

    def test_values_rejects_invalid_limit(self):
        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values?limit=not-a-number")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values?limit=0")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
