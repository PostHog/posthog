import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from products.metrics.backend.metric_names_query_runner import (
    MAX_PICKER_SERVICES,
    MetricNamesQueryRunner,
    cached_metric_names,
)
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

    def test_collapses_unmerged_series_parts_without_final(self):
        # Seeding twice lands two unmerged ReplacingMergeTree parts for one
        # fingerprint, which must still collapse to a single picker row.
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        for offset in (10, 1):
            seed_metric_event(
                team_id=self.team.id,
                metric_name="queue.depth",
                points=[(anchor - dt.timedelta(minutes=offset), 3.0)],
                metric_type="gauge",
            )

        # Sparklines are off so the row shape stays about the series collapse,
        # not the bucket grid.
        runner = MetricNamesQueryRunner(team=self.team, include_sparklines=False)
        self.assertEqual(
            runner.run(),
            [
                {
                    "name": "queue.depth",
                    "metric_type": "gauge",
                    "unit": "",
                    "last_seen": (anchor - dt.timedelta(minutes=1)).isoformat(),
                    "sparkline": [],
                }
            ],
        )

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

            # Nor may a service scope: the unscoped list is capped at `limit`, so
            # serving it to a scoped picker both widens and truncates the answer.
            run.return_value = [{"name": "m3", "metric_type": "gauge"}]
            self.assertEqual(cached_metric_names(self.team, services=["web"]), run.return_value)
            self.assertEqual(run.call_count, 3)
            # Same scope twice is one query; a different scope is its own entry.
            self.assertEqual(cached_metric_names(self.team, services=["web"]), run.return_value)
            self.assertEqual(run.call_count, 3)
            self.assertEqual(cached_metric_names(self.team, services=["worker"]), run.return_value)
            self.assertEqual(run.call_count, 4)

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

    def test_rejects_more_services_than_the_cap(self):
        with self.assertRaises(ValueError):
            MetricNamesQueryRunner(team=self.team, services=[f"svc-{i}" for i in range(MAX_PICKER_SERVICES + 1)])

    def _seed_two_services_and_an_unnamed_sender(self) -> None:
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        for service, metric_name in (("web", "http.duration"), ("worker", "jobs.processed"), ("", "orphan.metric")):
            seed_metric(
                team_id=self.team.id,
                metric_name=metric_name,
                points=[(anchor, 1.0)],
                service_name=service,
            )

    @parameterized.expand(
        [
            ("one service", ["web"], {"http.duration"}),
            ("several services", ["web", "worker"], {"http.duration", "jobs.processed"}),
            # An empty service name is a real group, not "no filter": a sender that
            # omits the `service.name` resource attribute lands here.
            ("the unnamed sender group", [""], {"orphan.metric"}),
            ("no scope", [], {"http.duration", "jobs.processed", "orphan.metric"}),
        ]
    )
    def test_scopes_names_to_the_selected_services(self, _name: str, services: list[str], expected: set[str]):
        self._seed_two_services_and_an_unnamed_sender()

        runner = MetricNamesQueryRunner(team=self.team, services=services)
        self.assertEqual({row["name"] for row in runner.run()}, expected)


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

    @parameterized.expand(
        [
            # Omitting the param and sending it empty mean different things, and the
            # only thing carrying that difference over the wire is the query string.
            ("omitted", "", {"http.duration", "jobs.processed", "orphan.metric"}),
            ("one service", "&service=web", {"http.duration"}),
            ("several services", "&service=web,worker", {"http.duration", "jobs.processed"}),
            ("empty, the unnamed sender group", "&service=", {"orphan.metric"}),
        ]
    )
    def test_values_service_param(self, _name: str, query: str, expected: set[str]):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        for service, metric_name in (("web", "http.duration"), ("worker", "jobs.processed"), ("", "orphan.metric")):
            seed_metric(
                team_id=self.team.id,
                metric_name=metric_name,
                points=[(anchor, 1.0)],
                service_name=service,
            )

        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values?limit=100{query}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({row["name"] for row in response.json()["results"]}, expected)

    def test_values_rejects_invalid_limit(self):
        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values?limit=not-a-number")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values?limit=0")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestMetricCatalogQueryRunner(ClickhouseTestMixin, APIBaseTest):
    """The catalog is the picker row plus what makes a card scannable: the unit,
    when the metric was last heard from, and a small sparkline of its recent
    shape. Sparkline points come from the raw `metrics` data points."""

    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        truncate_metrics_tables()
        cache.clear()

    def test_catalog_row_carries_unit_and_last_seen(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        seed_metric(
            team_id=self.team.id,
            metric_name="http.server.duration",
            points=[(anchor, 1.0)],
            metric_type="histogram",
            unit="ms",
        )

        runner = MetricNamesQueryRunner(team=self.team)
        row = next(r for r in runner.run() if r["name"] == "http.server.duration")

        self.assertEqual(row["unit"], "ms")
        # last_seen is an ISO string so the API layer can pass it straight through.
        self.assertIn("T", row["last_seen"])

    def test_sparkline_reflects_the_metric_shape(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=30)
        # A clear rise across the window: any faithful downsampling keeps the
        # last value above the first.
        points = [(anchor + dt.timedelta(minutes=i), float(i)) for i in range(30)]
        seed_metric_event(team_id=self.team.id, metric_name="queue.depth", points=points, metric_type="gauge")

        runner = MetricNamesQueryRunner(team=self.team)
        row = next(r for r in runner.run() if r["name"] == "queue.depth")

        sparkline = row["sparkline"]
        self.assertGreater(len(sparkline), 1)
        self.assertLess(sparkline[0], sparkline[-1])

    def test_sparkline_is_bounded(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=120)
        points = [(anchor + dt.timedelta(minutes=i), float(i % 7)) for i in range(120)]
        seed_metric_event(team_id=self.team.id, metric_name="busy.metric", points=points, metric_type="gauge")

        runner = MetricNamesQueryRunner(team=self.team)
        row = next(r for r in runner.run() if r["name"] == "busy.metric")

        # The bound is only meaningful against a card that has data to draw.
        self.assertGreater(len(row["sparkline"]), 1)
        self.assertLessEqual(len(row["sparkline"]), 24)

    def test_sparkline_draws_from_a_short_recent_run(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=20)
        points = [(anchor + dt.timedelta(minutes=i), float(i)) for i in range(10)]
        seed_metric_event(team_id=self.team.id, metric_name="samples.only", points=points, metric_type="gauge")

        runner = MetricNamesQueryRunner(team=self.team)
        row = next(r for r in runner.run() if r["name"] == "samples.only")

        self.assertGreater(len(row["sparkline"]), 1)
        self.assertLess(row["sparkline"][0], row["sparkline"][-1])

    def test_metric_with_no_samples_has_empty_sparkline(self):
        # Samples older than the sparkline window leave the series row (and so
        # the card) in place but give it nothing to draw.
        old_anchor = timezone.now().replace(microsecond=0) - dt.timedelta(hours=10)
        seed_metric(
            team_id=self.team.id,
            metric_name="old.metric",
            points=[(old_anchor, 1.0)],
            metric_type="gauge",
        )

        runner = MetricNamesQueryRunner(team=self.team)
        row = next(r for r in runner.run() if r["name"] == "old.metric")

        self.assertEqual(row["sparkline"], [])

    def test_sparkline_scoped_to_services(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=20)
        for service, metric_name in (("web", "http.duration"), ("worker", "jobs.processed")):
            seed_metric_event(
                team_id=self.team.id,
                metric_name=metric_name,
                points=[(anchor + dt.timedelta(minutes=i), float(i)) for i in range(10)],
                service_name=service,
            )

        runner = MetricNamesQueryRunner(team=self.team, services=["web"])
        rows = runner.run()

        self.assertEqual([r["name"] for r in rows], ["http.duration"])
        self.assertGreater(len(rows[0]["sparkline"]), 1)

    def test_sparkline_excludes_other_services_series(self):
        # web and worker emit the same metric name. A card scoped to web must
        # draw only web's series; an unscoped card averages both.
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=20)
        seed_metric_event(
            team_id=self.team.id,
            metric_name="shared.metric",
            points=[(anchor + dt.timedelta(minutes=i), 100.0) for i in range(10)],
            metric_type="gauge",
            service_name="web",
        )
        seed_metric_event(
            team_id=self.team.id,
            metric_name="shared.metric",
            points=[(anchor + dt.timedelta(minutes=i), 1.0) for i in range(10)],
            metric_type="gauge",
            service_name="worker",
        )

        web_row = next(r for r in MetricNamesQueryRunner(team=self.team, services=["web"]).run())
        all_row = next(r for r in MetricNamesQueryRunner(team=self.team).run())

        # Non-empty first: `all()` on an empty sparkline passes vacuously, which
        # is how the unscoped-averaging bug slipped through before.
        self.assertGreater(len(web_row["sparkline"]), 1)
        self.assertGreater(len(all_row["sparkline"]), 1)
        self.assertTrue(all(v == 100.0 for v in web_row["sparkline"]))
        self.assertTrue(all(v < 100.0 for v in all_row["sparkline"]))

    def test_runner_can_skip_the_sparkline_scan(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        _seed_point(team_id=self.team.id, metric_name="m1", value=1.0, timestamp=anchor)

        with patch("products.metrics.backend.metric_names_query_runner.execute_hogql_query") as execute:
            execute.return_value.results = [("m1", "gauge", "", timezone.now())]
            rows = MetricNamesQueryRunner(team=self.team, include_sparklines=False).run()

        # One query for the names, none for the samples.
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(rows[0]["sparkline"], [])
