import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from products.metrics.backend.metric_names_query_runner import MetricNamesQueryRunner, cached_metric_names
from products.metrics.backend.tests._seeder import seed_metric, seed_metric_event, truncate_metrics_tables


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
        truncate_metrics_tables()
        cache.clear()

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
        # A distinct label-set, so this is a second series under the same name —
        # otherwise the two seeds collapse to one series row and the GROUP BY
        # never has to do anything.
        seed_metric(
            team_id=self.team.id,
            metric_name="http.server.duration",
            points=[(anchor, 2.0)],
            metric_type="histogram",
            labels={"route": "/checkout"},
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

    @parameterized.expand(
        [
            ("substring", "server", ["http.server.duration"]),
            # '_' and '%' are ILIKE wildcards. Prometheus names are full of
            # underscores, so an unescaped search matches far too much.
            ("underscore_is_literal", "a_b", ["a_b"]),
            ("percent_is_literal", "c%d", ["c%d"]),
        ]
    )
    def test_search_filters_by_substring(self, _name: str, search: str, expected: list[str]):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        for metric_name in ("http.server.duration", "queue.depth", "a_b", "axb", "c%d", "cxxd"):
            _seed_point(team_id=self.team.id, metric_name=metric_name, value=1.0, timestamp=anchor)

        runner = MetricNamesQueryRunner(team=self.team, search=search)
        self.assertEqual([row["name"] for row in runner.run()], expected)

    def test_reads_series_written_without_a_raw_datapoint_row(self):
        # seed_metric_event writes metric_series1 + metric_samples1 and no metrics1
        # row, so this is the one test that fails if the runner goes back to
        # aggregating posthog.metrics. Seeding twice lands two unmerged
        # ReplacingMergeTree parts for one fingerprint, which must still collapse
        # to a single picker row without FINAL.
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        for offset in (10, 1):
            seed_metric_event(
                team_id=self.team.id,
                metric_name="queue.depth",
                points=[(anchor - dt.timedelta(minutes=offset), 3.0)],
                metric_type="gauge",
            )

        runner = MetricNamesQueryRunner(team=self.team)
        self.assertEqual(runner.run(), [{"name": "queue.depth", "metric_type": "gauge"}])

    def test_cache_covers_the_unsearched_list_only(self):
        with patch.object(MetricNamesQueryRunner, "run") as run:
            run.return_value = [{"name": "m1", "metric_type": "gauge"}]
            self.assertEqual(cached_metric_names(self.team), run.return_value)
            self.assertEqual(cached_metric_names(self.team), run.return_value)
            self.assertEqual(run.call_count, 1)

            # A search must never be answered from the unsearched list's cache.
            run.return_value = [{"name": "m2", "metric_type": "sum"}]
            self.assertEqual(cached_metric_names(self.team, search="m2"), run.return_value)
            self.assertEqual(run.call_count, 2)

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
        truncate_metrics_tables()
        cache.clear()

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
