import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute

from products.metrics.backend.facade.api import list_metric_picker_names
from products.metrics.backend.facade.contracts import MAX_SPARKLINE_BATCH_SIZE
from products.metrics.backend.metric_names_query_runner import (
    MAX_PICKER_SERVICES,
    MetricNamesQueryRunner,
    cached_metric_names,
    fold_classic_histograms,
    name_matches,
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

    def test_returns_metric_type_for_more_names_than_the_default_row_limit(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        for index in range(105):
            _seed_point(team_id=self.team.id, metric_name=f"m{index:03d}", value=1.0, timestamp=anchor)

        results = MetricNamesQueryRunner(team=self.team, limit=200).run()

        self.assertEqual(len(results), 105)
        self.assertEqual({row["metric_type"] for row in results}, {"gauge"})

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

    def test_picker_names_do_not_cache(self):
        with patch.object(MetricNamesQueryRunner, "run_picker") as run_picker:
            run_picker.return_value = [{"name": "m1", "metric_type": "gauge"}]
            self.assertEqual(list_metric_picker_names(team=self.team), run_picker.return_value)
            self.assertEqual(list_metric_picker_names(team=self.team), run_picker.return_value)
            self.assertEqual(run_picker.call_count, 2)

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

    @parameterized.expand(
        [
            (
                "search ranks exact, prefix, suffix, then service count, then name",
                "HTTP",
                [],
                ["http", "http.requests", "server.http", "b.http.x", "a.http.x", "c.http.x"],
            ),
            (
                "no search ranks by service count, then name",
                "",
                [],
                ["b.http.x", "a.http.x", "c.http.x", "http", "http.requests", "other", "server.http"],
            ),
            (
                "service scope counts the selected services only",
                "",
                ["web"],
                ["a.http.x", "b.http.x", "c.http.x", "http", "server.http"],
            ),
        ]
    )
    def test_sort_order(self, _name: str, search: str, services: list[str], expected: list[str]):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        for metric_name, metric_services in (
            ("c.http.x", ["web"]),
            ("a.http.x", ["web"]),
            ("b.http.x", ["web", "worker"]),
            ("server.http", ["web"]),
            ("http.requests", ["worker"]),
            ("http", ["web"]),
            ("other", ["worker"]),
        ):
            for service in metric_services:
                seed_metric(team_id=self.team.id, metric_name=metric_name, points=[(anchor, 1.0)], service_name=service)

        runner = MetricNamesQueryRunner(team=self.team, search=search, services=services, include_sparklines=False)
        self.assertEqual([row["name"] for row in runner.run()], expected)

    def test_respects_team_isolation(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        _seed_point(team_id=99999, metric_name="other.team.metric", value=1.0, timestamp=anchor)

        runner = MetricNamesQueryRunner(team=self.team)
        self.assertEqual(runner.run(), [])

    def test_lookback_excludes_old_data(self):
        old = timezone.now().replace(microsecond=0) - dt.timedelta(days=2)
        recent = timezone.now().replace(microsecond=0) - dt.timedelta(hours=1)
        _seed_point(team_id=self.team.id, metric_name="old.metric", value=1.0, timestamp=old)
        _seed_point(team_id=self.team.id, metric_name="recent.metric", value=2.0, timestamp=recent)

        runner = MetricNamesQueryRunner(team=self.team)
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

    def _seed_names(self, names: list[str]) -> None:
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        for metric_name in names:
            _seed_point(team_id=self.team.id, metric_name=metric_name, value=1.0, timestamp=anchor)

    @parameterized.expand(
        [
            # A substring search for "lag" also matches every "flag" name.
            ("substring", "lag", "substring", ["lag", "lag_seconds", "consumer_lag", "flag_count", "flags"]),
            ("prefix", "lag", "prefix", ["lag", "lag_seconds"]),
            ("prefix_is_case_insensitive", "LAG", "prefix", ["lag", "lag_seconds"]),
            ("prefix_underscore_is_literal", "lag_", "prefix", ["lag_seconds"]),
            ("regex_anchored_suffix", "(^|_)lag(_|$)", "regex", ["consumer_lag", "lag", "lag_seconds"]),
            ("regex_is_case_sensitive", "^LAG", "regex", []),
            ("regex_case_flag", "(?i)^LAG$", "regex", ["lag"]),
        ]
    )
    def test_search_match_modes(self, _name: str, search: str, match: str, expected: list[str]):
        self._seed_names(["lag", "lag_seconds", "consumer_lag", "flag_count", "flags", "queue.depth"])

        runner = MetricNamesQueryRunner(team=self.team, search=search, match=match, include_sparklines=False)
        self.assertEqual([row["name"] for row in runner.run()], expected)

    @parameterized.expand([("unknown_mode", "lag", "glob"), ("invalid_regex", "(unclosed", "regex")])
    def test_rejects_bad_match(self, _name: str, search: str, match: str):
        with self.assertRaises(ValueError):
            MetricNamesQueryRunner(team=self.team, search=search, match=match)

    def test_first_seen_reaches_past_the_lookback(self):
        now = timezone.now().replace(microsecond=0)
        three_days_ago = now - dt.timedelta(days=3, minutes=10)
        two_hours_ago = now - dt.timedelta(hours=2, minutes=10)
        _seed_point(team_id=self.team.id, metric_name="old.metric", value=1.0, timestamp=three_days_ago)
        _seed_point(team_id=self.team.id, metric_name="old.metric", value=1.0, timestamp=now - dt.timedelta(minutes=5))
        _seed_point(team_id=self.team.id, metric_name="new.metric", value=1.0, timestamp=two_hours_ago)

        rows = MetricNamesQueryRunner(team=self.team, include_sparklines=False, include_first_seen=True).run()

        first_seen = {row["name"]: dt.datetime.fromisoformat(row["first_seen"]) for row in rows}
        self.assertEqual(first_seen["old.metric"], three_days_ago.replace(minute=0, second=0))
        self.assertEqual(first_seen["new.metric"], two_hours_ago.replace(minute=0, second=0))

    def test_first_seen_is_opt_in(self):
        self._seed_names(["queue.depth"])
        with patch(
            "products.metrics.backend.metric_names_query_runner.execute_hogql_query", wraps=execute_hogql_query
        ) as execute:
            rows = MetricNamesQueryRunner(team=self.team, include_sparklines=False).run()
        self.assertNotIn("first_seen", rows[0])
        self.assertEqual(execute.call_count, 1)

    def test_skipping_sparklines_runs_one_query(self):
        self._seed_names(["queue.depth"])
        with patch(
            "products.metrics.backend.metric_names_query_runner.execute_hogql_query", wraps=execute_hogql_query
        ) as execute:
            rows = MetricNamesQueryRunner(team=self.team, include_sparklines=False).run()
        self.assertEqual(rows[0]["sparkline"], [])
        self.assertEqual(execute.call_count, 1)


class TestNameMatches(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty_matches_all", "logs.count", "", "substring", True),
            ("substring", "logs.error_count", "ERROR", "substring", True),
            ("prefix_hit", "logs.count", "LOGS.", "prefix", True),
            ("prefix_miss", "spans.logs", "logs", "prefix", False),
            ("regex_hit", "spans.duration", "^spans\\.", "regex", True),
            ("regex_case_sensitive", "spans.duration", "^SPANS", "regex", False),
        ]
    )
    def test_name_matches(self, _name: str, name: str, search: str, match: str, expected: bool):
        self.assertEqual(name_matches(name, search, match), expected)


class TestFoldClassicHistograms(SimpleTestCase):
    def _row(self, name: str, last_seen: str, first_seen: str | None = None) -> dict:
        row = {"name": name, "metric_type": "sum", "unit": "", "last_seen": last_seen, "sparkline": []}
        if first_seen is not None:
            row["first_seen"] = first_seen
        return row

    def test_folds_a_complete_triple_into_the_bucket_row(self):
        rows = [
            self._row("lag_seconds_count", "2026-01-01T00:03:00+00:00", "2026-01-01T00:00:00+00:00"),
            self._row("lag_seconds_bucket", "2026-01-01T00:01:00+00:00", "2025-12-31T23:00:00+00:00"),
            self._row("queue_depth", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            self._row("lag_seconds_sum", "2026-01-01T00:02:00+00:00", "2026-01-01T00:00:00+00:00"),
        ]

        folded = fold_classic_histograms(rows)

        self.assertEqual([row["name"] for row in folded], ["lag_seconds_bucket", "queue_depth"])
        self.assertEqual(
            folded[0]["classic_histogram"],
            {
                "base_name": "lag_seconds",
                "bucket": "lag_seconds_bucket",
                "sum": "lag_seconds_sum",
                "count": "lag_seconds_count",
            },
        )
        self.assertEqual(folded[0]["last_seen"], "2026-01-01T00:03:00+00:00")
        self.assertEqual(folded[0]["first_seen"], "2025-12-31T23:00:00+00:00")
        self.assertNotIn("classic_histogram", folded[1])

    @parameterized.expand(
        [
            ("missing_sum", ["x_bucket", "x_count"]),
            ("missing_bucket", ["x_sum", "x_count"]),
            ("bare_suffixes", ["_bucket", "_sum", "_count"]),
        ]
    )
    def test_leaves_an_incomplete_triple_alone(self, _name: str, names: list[str]):
        rows = [self._row(name, "2026-01-01T00:00:00+00:00") for name in names]
        self.assertEqual(fold_classic_histograms(rows), rows)

    def test_leaves_gauges_with_histogram_suffixes_alone(self):
        rows = [
            {**self._row(name, "2026-01-01T00:00:00+00:00"), "metric_type": "gauge"}
            for name in ["x_bucket", "x_sum", "x_count"]
        ]
        self.assertEqual(fold_classic_histograms(rows), rows)

    def test_keeps_a_native_histogram_beside_its_classic_triple(self):
        rows = [
            {**self._row("x", "2026-01-01T00:00:00+00:00"), "metric_type": "histogram"},
            self._row("x_bucket", "2026-01-01T00:00:00+00:00"),
            self._row("x_sum", "2026-01-01T00:00:00+00:00"),
            self._row("x_count", "2026-01-01T00:00:00+00:00"),
        ]
        self.assertEqual([row["name"] for row in fold_classic_histograms(rows)], ["x", "x_bucket"])


class TestMetricsValuesAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        truncate_metrics_tables()
        cache.clear()

    @parameterized.expand([("get",), ("post",)])
    def test_values_requires_authentication(self, method):
        self.client.logout()
        response = getattr(self.client, method)(f"/api/projects/{self.team.id}/metrics/values")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_values_returns_empty_for_no_data(self):
        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"results": []})

    @parameterized.expand([("finite", 1.0), ("overflowing_average", 1e308)])
    def test_values_returns_metric_names(self, _name: str, value: float):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        earlier = anchor - dt.timedelta(minutes=20)
        _seed_point(team_id=self.team.id, metric_name="m1", value=value, timestamp=earlier)
        seed_metric(team_id=self.team.id, metric_name="m1", points=[(earlier, value)], labels={"shard": "other"})
        _seed_point(team_id=self.team.id, metric_name="m1", value=1.0, timestamp=anchor)
        _seed_point(team_id=self.team.id, metric_name="m2", value=2.0, timestamp=anchor, metric_type="gauge")

        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        names = {row["name"] for row in body["results"]}
        self.assertEqual(names, {"m1", "m2"})
        self.assertIn("sparkline", body["results"][0])
        sparkline = next(row["sparkline"] for row in body["results"] if row["name"] == "m1")
        self.assertEqual(sparkline, [1.0, 1.0] if value == 1.0 else [1.0])

    def test_names_returns_picker_fields_only(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        _seed_point(team_id=self.team.id, metric_name="m1", value=1.0, timestamp=anchor)

        with patch(
            "products.metrics.backend.metric_names_query_runner.execute_hogql_query", wraps=execute_hogql_query
        ) as execute:
            response = self.client.get(f"/api/projects/{self.team.id}/metrics/names/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"results": [{"name": "m1", "metric_type": "gauge"}]})
        self.assertEqual(execute.call_count, 1)
        self.assertNotIn("metric_series", str(execute.call_args.kwargs["query"]))

    def test_values_search_param(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        _seed_point(team_id=self.team.id, metric_name="http.duration", value=1.0, timestamp=anchor)
        _seed_point(team_id=self.team.id, metric_name="queue.depth", value=2.0, timestamp=anchor)

        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values?value=http")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in response.json()["results"]]
        self.assertEqual(names, ["http.duration"])

    def test_values_batch_matches_exact_names_and_service(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        for metric_name, service in [
            ("queue.depth", "web"),
            ("queue.depth.extra", "web"),
            ("http.duration", "web"),
            ("worker.count", "worker"),
        ]:
            seed_metric(
                team_id=self.team.id,
                metric_name=metric_name,
                points=[(anchor - dt.timedelta(minutes=20), 1.0), (anchor, 2.0)],
                service_name=service,
            )
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/values/",
            {
                "names": ["queue.depth", "http.duration", "worker.count", "missing.metric"],
                "service": "web",
                "limit": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.json()["results"]
        self.assertEqual({row["name"] for row in rows}, {"queue.depth", "http.duration"})
        for row in rows:
            self.assertEqual(row["sparkline"], [1.0, 2.0])

    @parameterized.expand(
        [
            ("empty", []),
            ("too many", [f"metric.{index}" for index in range(MAX_SPARKLINE_BATCH_SIZE + 1)]),
            ("blank", [""]),
            ("too long", ["a" * 256]),
        ]
    )
    def test_values_rejects_invalid_names(self, _name, names):
        response = self.client.post(f"/api/projects/{self.team.id}/metrics/values/", {"names": names}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

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

    def test_values_mcp_shape(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        for metric_name in ("lag_seconds_bucket", "lag_seconds_sum", "lag_seconds_count", "flag_count"):
            _seed_point(team_id=self.team.id, metric_name=metric_name, value=1.0, timestamp=anchor, metric_type="sum")

        response = self.client.get(
            f"/api/projects/{self.team.id}/metrics/values/"
            "?value=lag&match=prefix&sparklines=false&first_seen=true&fold_histograms=true"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.json()["results"]
        self.assertEqual([row["name"] for row in rows], ["lag_seconds_bucket"])
        self.assertEqual(rows[0]["sparkline"], [])
        self.assertEqual(rows[0]["classic_histogram"]["sum"], "lag_seconds_sum")
        self.assertEqual(
            dt.datetime.fromisoformat(rows[0]["first_seen"]), anchor.replace(minute=0, second=0, microsecond=0)
        )

    def test_values_defaults_keep_the_catalog_shape(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        for metric_name in ("x_bucket", "x_sum", "x_count"):
            _seed_point(team_id=self.team.id, metric_name=metric_name, value=1.0, timestamp=anchor)

        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.json()["results"]
        self.assertEqual({row["name"] for row in rows}, {"x_bucket", "x_sum", "x_count"})
        for row in rows:
            self.assertEqual(set(row), {"name", "metric_type", "unit", "last_seen", "sparkline"})

    @parameterized.expand([("unknown_match", "?value=x&match=glob"), ("invalid_regex", "?value=(x&match=regex")])
    def test_values_rejects_bad_match(self, _name: str, query: str):
        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values/{query}")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

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

    def test_catalog_page_is_not_cut_at_the_default_query_limit(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        for i in range(101):
            _seed_point(team_id=self.team.id, metric_name=f"m{i:03d}", value=1.0, timestamp=anchor)

        rows = MetricNamesQueryRunner(team=self.team, limit=150, include_sparklines=False).run()

        self.assertEqual(len(rows), 101)

    def test_every_name_in_a_batch_gets_a_sparkline(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(hours=6)
        names = [f"busy.{i:02d}" for i in range(MAX_SPARKLINE_BATCH_SIZE)]
        for name in names:
            points = [(anchor + dt.timedelta(minutes=15 * i + 1), float(i)) for i in range(24)]
            seed_metric_event(team_id=self.team.id, metric_name=name, points=points, metric_type="gauge")

        rows = MetricNamesQueryRunner(team=self.team, names=names).run()

        self.assertEqual({row["name"]: len(row["sparkline"]) > 1 for row in rows}, dict.fromkeys(names, True))

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
            execute.return_value = MagicMock(results=[("m1", "gauge", "", timezone.now())])
            rows = MetricNamesQueryRunner(team=self.team, include_sparklines=False).run()

        self.assertEqual(execute.call_count, 1)
        self.assertEqual(rows[0]["sparkline"], [])

    def test_name_without_a_series_row_keeps_empty_details(self):
        anchor = timezone.now().replace(microsecond=0) - dt.timedelta(minutes=5)
        _seed_point(team_id=self.team.id, metric_name="m1", value=1.0, timestamp=anchor)
        sync_execute("TRUNCATE TABLE IF EXISTS metrics4_series")

        rows = MetricNamesQueryRunner(team=self.team, include_sparklines=False).run()

        self.assertEqual(
            [(row["name"], row["metric_type"], row["unit"], row["last_seen"]) for row in rows],
            [("m1", "", "", None)],
        )
