import datetime as dt
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.schema import HogQLQueryResponse

from posthog.hogql.query import execute_hogql_query

from products.metrics.backend import metrics_overview_query_runner
from products.metrics.backend.metrics_overview_query_runner import MetricsOverviewQueryRunner
from products.metrics.backend.tests._seeder import seed_metric, seed_metric_event, truncate_metrics_tables


class TestMetricsOverviewQueryRunner(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        truncate_metrics_tables()

    def test_rejects_non_positive_lookback(self):
        with self.assertRaises(ValueError):
            MetricsOverviewQueryRunner(team=self.team, lookback=dt.timedelta(0))

    def test_returns_empty_overview_for_no_data(self):
        overview = MetricsOverviewQueryRunner(team=self.team).run()

        self.assertIsNone(overview.last_seen)
        self.assertEqual(overview.metric_names, 0)
        self.assertEqual(overview.series, 0)
        self.assertEqual(overview.services, ())

    @parameterized.expand(
        [
            ("all_services_listed", 500, ["api", "worker"]),
            ("services_list_truncated", 1, ["api"]),
        ]
    )
    def test_rolls_up_services_within_the_window(self, _name: str, max_services: int, expected_services: list[str]):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        seed_metric(team_id=self.team.id, metric_name="http.duration", points=[(anchor, 1.0)], service_name="api")
        seed_metric(
            team_id=self.team.id,
            metric_name="http.duration",
            points=[(anchor - dt.timedelta(minutes=1), 2.0)],
            labels={"route": "/checkout"},
            service_name="api",
        )
        seed_metric(team_id=self.team.id, metric_name="queue.depth", points=[(anchor, 3.0)], service_name="api")
        seed_metric(team_id=self.team.id, metric_name="jobs.processed", points=[(anchor, 4.0)], service_name="worker")

        with patch.object(metrics_overview_query_runner, "MAX_SERVICES", max_services):
            overview = MetricsOverviewQueryRunner(team=self.team).run()

        self.assertEqual(overview.metric_names, 3)
        self.assertEqual(overview.series, 4)
        assert overview.last_seen is not None
        self.assertEqual(dt.datetime.fromisoformat(overview.last_seen), anchor)

        self.assertEqual([s.service_name for s in overview.services], expected_services)
        api_row = overview.services[0]
        self.assertEqual(api_row.metric_names, 2)
        self.assertEqual(api_row.series, 3)
        self.assertEqual(dt.datetime.fromisoformat(api_row.last_seen), anchor)

    def test_last_seen_comes_from_the_newest_sample_not_the_series_row(self):
        newest = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        seed_metric(
            team_id=self.team.id,
            metric_name="http.duration",
            points=[(newest - dt.timedelta(minutes=20), 1.0)],
            service_name="api",
        )
        # Capture strips the labels from later samples in the label window, so the series row keeps the first sample time.
        seed_metric(
            team_id=self.team.id,
            metric_name="http.duration",
            points=[(newest, 2.0)],
            service_name="api",
            has_labels=False,
        )
        seed_metric(
            team_id=99999,
            metric_name="http.duration",
            points=[(newest + dt.timedelta(minutes=2), 3.0)],
            service_name="api",
            has_labels=False,
        )

        overview = MetricsOverviewQueryRunner(team=self.team).run()

        assert overview.last_seen is not None
        self.assertEqual(dt.datetime.fromisoformat(overview.last_seen), newest)
        self.assertEqual(
            [(s.service_name, dt.datetime.fromisoformat(s.last_seen)) for s in overview.services], [("api", newest)]
        )

    @parameterized.expand(
        [
            (
                "each_service_starts_from_its_own_series_last_seen",
                500,
                [
                    ("api", {}, 0, True),
                    ("worker", {}, 25, True),
                    ("worker", {}, 5, False),
                ],
                [("api", 0), ("worker", 5)],
            ),
            (
                "listed_services_are_picked_by_series_count_not_recency",
                1,
                [
                    ("api", {"route": "/a"}, 30, True),
                    ("api", {"route": "/b"}, 30, True),
                    ("api", {"route": "/a"}, 10, False),
                    ("worker", {}, 20, True),
                    ("worker", {}, 0, False),
                ],
                [("api", 10)],
            ),
        ]
    )
    def test_each_listed_service_reads_its_own_newest_sample(
        self,
        _name: str,
        max_services: int,
        seeds: list[tuple[str, dict[str, str], int, bool]],
        expected_services: list[tuple[str, int]],
    ):
        newest = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        for service_name, labels, minutes_before_newest, has_labels in seeds:
            seed_metric(
                team_id=self.team.id,
                metric_name="http.duration",
                points=[(newest - dt.timedelta(minutes=minutes_before_newest), 1.0)],
                labels=labels,
                service_name=service_name,
                has_labels=has_labels,
            )

        with patch.object(metrics_overview_query_runner, "MAX_SERVICES", max_services):
            overview = MetricsOverviewQueryRunner(team=self.team).run()

        assert overview.last_seen is not None
        self.assertEqual(dt.datetime.fromisoformat(overview.last_seen), newest)
        self.assertEqual(
            [(s.service_name, dt.datetime.fromisoformat(s.last_seen)) for s in overview.services],
            [(name, newest - dt.timedelta(minutes=minutes)) for name, minutes in expected_services],
        )

    def test_services_query_reads_the_hourly_projection(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        seed_metric(team_id=self.team.id, metric_name="http.duration", points=[(anchor, 1.0)], service_name="api")

        def force_projection(**kwargs: Any) -> HogQLQueryResponse:
            if kwargs["query_type"] == "MetricsOverviewServicesQuery":
                kwargs["settings"] = kwargs["settings"].model_copy(update={"force_optimize_projection": True})
            return execute_hogql_query(**kwargs)

        with patch.object(metrics_overview_query_runner, "execute_hogql_query", side_effect=force_projection):
            overview = MetricsOverviewQueryRunner(team=self.team).run()

        self.assertEqual([(s.service_name, s.series) for s in overview.services], [("api", 1)])

    def test_quiet_project_keeps_overall_last_seen_but_lists_no_services(self):
        stale = timezone.now().replace(microsecond=0) - dt.timedelta(days=3)
        seed_metric(team_id=self.team.id, metric_name="http.duration", points=[(stale, 1.0)], service_name="api")

        overview = MetricsOverviewQueryRunner(team=self.team, lookback=dt.timedelta(days=1)).run()

        assert overview.last_seen is not None
        self.assertEqual(dt.datetime.fromisoformat(overview.last_seen), stale)
        self.assertEqual(overview.metric_names, 0)
        self.assertEqual(overview.series, 0)
        self.assertEqual(overview.services, ())

    def test_window_excludes_stale_services(self):
        recent = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        stale = timezone.now().replace(microsecond=0) - dt.timedelta(days=3)
        seed_metric(team_id=self.team.id, metric_name="fresh.metric", points=[(recent, 1.0)], service_name="fresh")
        seed_metric(team_id=self.team.id, metric_name="old.metric", points=[(stale, 1.0)], service_name="stale")

        overview = MetricsOverviewQueryRunner(team=self.team, lookback=dt.timedelta(days=1)).run()

        self.assertEqual([s.service_name for s in overview.services], ["fresh"])
        self.assertEqual(overview.metric_names, 1)
        self.assertEqual(overview.series, 1)

    def test_dedupes_replacing_merge_tree_parts_without_final(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        for offset in (10, 1):
            seed_metric_event(
                team_id=self.team.id,
                metric_name="queue.depth",
                points=[(anchor - dt.timedelta(minutes=offset), 3.0)],
                metric_type="gauge",
                service_name="api",
            )

        overview = MetricsOverviewQueryRunner(team=self.team).run()

        self.assertEqual(overview.series, 1)
        self.assertEqual(overview.metric_names, 1)
        self.assertEqual([(s.service_name, s.series) for s in overview.services], [("api", 1)])

    def test_respects_team_isolation(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        seed_metric(team_id=99999, metric_name="other.team.metric", points=[(anchor, 1.0)])

        overview = MetricsOverviewQueryRunner(team=self.team).run()

        self.assertIsNone(overview.last_seen)
        self.assertEqual(overview.services, ())


class TestMetricsOverviewAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        truncate_metrics_tables()

    def test_overview_requires_authentication(self):
        self.client.logout()
        response = self.client.get(f"/api/projects/{self.team.id}/metrics/overview")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_overview_returns_empty_shape_for_no_data(self):
        response = self.client.get(f"/api/projects/{self.team.id}/metrics/overview")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertIsNone(body["last_seen"])
        self.assertEqual(body["services"], [])

    def test_overview_returns_service_rollup(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        seed_metric(team_id=self.team.id, metric_name="http.duration", points=[(anchor, 1.0)], service_name="api")

        response = self.client.get(f"/api/projects/{self.team.id}/metrics/overview")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["metric_names"], 1)
        self.assertEqual(body["series"], 1)
        self.assertGreater(body["lookback_seconds"], 0)
        self.assertEqual(len(body["services"]), 1)
        self.assertEqual(body["services"][0]["service_name"], "api")
        self.assertEqual(dt.datetime.fromisoformat(body["services"][0]["last_seen"]), anchor)
