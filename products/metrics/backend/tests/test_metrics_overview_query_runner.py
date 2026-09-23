import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from rest_framework import status

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

    def test_rolls_up_services_within_the_window(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        # "api" reports two series of one metric (distinct label-sets) plus a
        # second metric; "worker" reports one metric. Distinct label-sets are
        # what makes series != metric_names, so a runner that counts the wrong
        # column collapses one of the two numbers.
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

        overview = MetricsOverviewQueryRunner(team=self.team).run()

        self.assertEqual(overview.metric_names, 3)
        self.assertEqual(overview.series, 4)
        assert overview.last_seen is not None
        self.assertEqual(dt.datetime.fromisoformat(overview.last_seen), anchor)

        self.assertEqual([s.service_name for s in overview.services], ["api", "worker"])
        api_row = overview.services[0]
        self.assertEqual(api_row.metric_names, 2)
        self.assertEqual(api_row.series, 3)
        self.assertEqual(dt.datetime.fromisoformat(api_row.last_seen), anchor)

    def test_quiet_project_keeps_overall_last_seen_but_lists_no_services(self):
        # The ingestion-stopped case: data exists but nothing reported inside
        # the window. The status strip needs last_seen to say how long ago
        # ingestion stopped, while the window-scoped numbers go to zero.
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
        # Two seeds of one label-set land two unmerged ReplacingMergeTree parts
        # for one fingerprint; the overview must still count one series.
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
