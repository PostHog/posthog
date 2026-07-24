from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

import dagster
from parameterized import parameterized

from posthog.clickhouse.query_tagging import Feature, get_query_tags, reset_query_tags, tag_queries

from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import is_background_warming_request
from products.web_analytics.dags.cache_warming import (
    build_replay_runner,
    get_warmable_queries_op,
    maybe_expand_warming_date_range,
    maybe_opt_into_lazy_precompute,
    queries_to_keep_fresh,
    warm_queries_op,
)


class TestMaybeOptIntoLazyPrecompute(BaseTest):
    def test_web_query_gets_opt_in(self) -> None:
        # If this breaks, the warmer silently stops building precompute buckets
        # for replayed shapes wherever the opt-in default still applies.
        query = {"kind": "WebStatsTableQuery", "properties": []}
        result = maybe_opt_into_lazy_precompute(query)

        self.assertIs(result["useWebAnalyticsPrecompute"], True)
        self.assertNotIn("useWebAnalyticsPrecompute", query)  # input not mutated

    @parameterized.expand(
        [
            # Non-web kinds don't carry the field; injecting it would break validation.
            ("non_web_kind", {"kind": "TrendsQuery"}),
            # An explicit user opt-out in the replayed shape is preserved.
            ("explicit_opt_out", {"kind": "WebStatsTableQuery", "useWebAnalyticsPrecompute": False}),
            ("explicit_opt_in", {"kind": "WebOverviewQuery", "useWebAnalyticsPrecompute": True}),
        ]
    )
    def test_leaves_query_untouched(self, _name: str, query: dict) -> None:
        self.assertEqual(maybe_opt_into_lazy_precompute(query), query)


class TestMaybeExpandWarmingDateRange(BaseTest):
    @parameterized.expand(
        [
            # Sub-30d ranges deepen to -30d; if these stop expanding, warming
            # silently builds only ~7 days and every -14d/-28d request
            # cold-builds inline.
            ("default_7d", {"date_from": "-7d"}, "-30d"),
            ("today", {"date_from": "dStart"}, "-30d"),
            ("hours", {"date_from": "-24h"}, "-30d"),
            ("weeks", {"date_from": "-2w"}, "-30d"),
            ("no_date_range", None, "-30d"),
            # Wider or absolute ranges must stay exact — expanding would shrink
            # or shift what the user actually asked to precompute.
            ("ninety_days", {"date_from": "-90d"}, "-90d"),
            ("hours_over_30d", {"date_from": "-1000h"}, "-1000h"),
            ("weeks_over_30d", {"date_from": "-5w"}, "-5w"),
            ("one_month_can_be_31d", {"date_from": "-1m"}, "-1m"),
            ("all_time", {"date_from": "all"}, "all"),
            ("absolute", {"date_from": "2026-07-01T00:00:00"}, "2026-07-01T00:00:00"),
            ("month_start", {"date_from": "mStart"}, "mStart"),
        ]
    )
    def test_expansion(self, _name: str, date_range: dict | None, expected_date_from: str) -> None:
        query: dict = {"kind": "WebOverviewQuery", "useWebAnalyticsPrecompute": True}
        if date_range is not None:
            query["dateRange"] = date_range

        result = maybe_expand_warming_date_range(query)

        self.assertEqual(result["dateRange"]["date_from"], expected_date_from)

    def test_preserves_date_to_and_other_range_keys(self) -> None:
        query = {
            "kind": "WebStatsTableQuery",
            "useWebAnalyticsPrecompute": True,
            "dateRange": {"date_from": "-1dStart", "date_to": "-1dEnd", "explicitDate": True},
        }

        result = maybe_expand_warming_date_range(query)

        self.assertEqual(result["dateRange"], {"date_from": "-30d", "date_to": "-1dEnd", "explicitDate": True})

    @parameterized.expand(
        [
            # An opted-out shape replays on the raw path where the exact
            # result-cache row is the whole value of warming it.
            (
                "opted_out",
                {"kind": "WebOverviewQuery", "useWebAnalyticsPrecompute": False, "dateRange": {"date_from": "-7d"}},
            ),
            ("non_lazy_kind", {"kind": "WebExternalClicksTableQuery", "dateRange": {"date_from": "-7d"}}),
        ]
    )
    def test_leaves_non_precompute_replays_untouched(self, _name: str, query: dict) -> None:
        self.assertEqual(maybe_expand_warming_date_range(query), query)


class TestBuildReplayRunner(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The warm op tags before building runners; the enrollment gate treats
        # tagged warming requests as enabled, so tests must run under the same
        # tags to exercise the production decision.
        tag_queries(team_id=self.team.pk, trigger="webAnalyticsQueryWarming", feature=Feature.CACHE_WARMUP)

    def tearDown(self) -> None:
        reset_query_tags()
        super().tearDown()

    def test_lazy_eligible_shape_keeps_widened_range(self) -> None:
        # Under the warming tag even a non-enrolled team widens: building
        # buckets for not-yet-enrolled teams is the warmer's purpose.
        query = {
            "kind": "WebOverviewQuery",
            "properties": [],
            "useWebAnalyticsPrecompute": True,
            "dateRange": {"date_from": "-7d"},
        }

        runner, used_json, lazy_eligible = build_replay_runner(self.team, query)

        self.assertIsNotNone(runner)
        self.assertTrue(lazy_eligible)
        self.assertEqual(used_json["dateRange"]["date_from"], "-30d")

    @parameterized.expand(
        [
            # Shapes every lazy family rejects execute on the raw path — a
            # widened replay there is a 30-day scan the tenant never ran,
            # outside their request throttles. If this stops falling back, the
            # warmer becomes a background-load amplifier for mintable
            # ineligible shapes.
            ("conversion_goal", {"kind": "WebOverviewQuery", "conversionGoal": {"customEventName": "purchase"}}),
            # Passes the shared gate; rejected by all three stats families
            # (paths/frustration: wrong breakdown, simple: bounce rate).
            (
                "bounce_rate_browser",
                {"kind": "WebStatsTableQuery", "breakdownBy": "Browser", "includeBounceRate": True},
            ),
        ]
    )
    def test_family_rejected_shape_replays_faithful_range(self, _name: str, extra: dict) -> None:
        query = {
            "properties": [],
            "useWebAnalyticsPrecompute": True,
            "dateRange": {"date_from": "-7d"},
            **extra,
        }

        runner, used_json, lazy_eligible = build_replay_runner(self.team, query)

        self.assertIsNotNone(runner)
        self.assertFalse(lazy_eligible)
        self.assertEqual(used_json["dateRange"]["date_from"], "-7d")

    def test_outside_warming_context_gate_fails_closed(self) -> None:
        reset_query_tags()
        query = {
            "kind": "WebOverviewQuery",
            "properties": [],
            "useWebAnalyticsPrecompute": True,
            "dateRange": {"date_from": "-7d"},
        }

        runner, used_json, lazy_eligible = build_replay_runner(self.team, query)

        self.assertIsNotNone(runner)
        self.assertFalse(lazy_eligible)
        self.assertEqual(used_json["dateRange"]["date_from"], "-7d")


class TestFleetQuerySelection(BaseTest):
    @patch("products.web_analytics.dags.cache_warming.sync_execute")
    def test_parses_fleet_rows_into_query_infos(self, mock_exec: MagicMock) -> None:
        # Guards the row-shape contract with the selection SQL: a column reorder
        # or JSON handling change would make the warmer warm nothing or crash.
        mock_exec.return_value = [
            (101, '{"kind": "WebOverviewQuery"}', 50, "hash-a"),
            (202, '{"kind": "WebStatsTableQuery"}', 12, "hash-b"),
        ]
        result = queries_to_keep_fresh(dagster.build_op_context(), days=7, minimum_query_count=10, max_shapes=100)

        self.assertEqual(
            result,
            [
                {
                    "team_id": 101,
                    "query_json": {"kind": "WebOverviewQuery"},
                    "query_count": 50,
                    "normalized_query_hash": "hash-a",
                },
                {
                    "team_id": 202,
                    "query_json": {"kind": "WebStatsTableQuery"},
                    "query_count": 12,
                    "normalized_query_hash": "hash-b",
                },
            ],
        )

    @patch("products.web_analytics.dags.cache_warming.sync_execute", return_value=[])
    def test_selection_sql_survives_driver_percent_formatting(self, mock_exec: MagicMock) -> None:
        # clickhouse_driver %-formats the query when params are passed, so literal
        # % (the LIKE prefilter) must be written as %%. A bare % would crash only
        # in production, because tests mock sync_execute away.
        queries_to_keep_fresh(dagster.build_op_context(), days=2, minimum_query_count=10, max_shapes=100)

        sql, params = mock_exec.call_args[0]
        rendered = sql % dict.fromkeys(params, "1")  # what the driver's substitution does

        self.assertIn("LIKE '%Web%'", rendered)
        self.assertIn("system.query_log", rendered)

    @patch("products.web_analytics.dags.cache_warming._read_cached_warmable_queries", return_value=None)
    @patch("products.web_analytics.dags.cache_warming._write_cached_warmable_queries")
    @patch("products.web_analytics.dags.cache_warming.sync_execute", return_value=[])
    def test_op_reads_instance_settings(
        self, _mock_exec: MagicMock, _mock_write: MagicMock, _mock_read: MagicMock
    ) -> None:
        # Runs the op against the real instance-setting machinery so a renamed or
        # unregistered setting key fails here instead of at the hourly run. Cache
        # forced to miss so the assertion doesn't depend on Redis state.
        result = get_warmable_queries_op(dagster.build_op_context())
        self.assertEqual(result, [])


class _FakeObjectStorage:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def read_bytes(self, key: str, bucket: str | None = None, *, missing_ok: bool = False) -> bytes | None:
        return self.store.get(key)

    def write(self, key: str, content: bytes, extras: dict | None = None, bucket: str | None = None) -> None:
        self.store[key] = content


class TestWarmableQueriesCaching(BaseTest):
    @patch("products.web_analytics.dags.cache_warming.object_storage", new_callable=_FakeObjectStorage)
    @patch("products.web_analytics.dags.cache_warming.sync_execute")
    def test_second_run_reuses_cached_selection(self, mock_exec: MagicMock, _storage: _FakeObjectStorage) -> None:
        # The whole reason this cache exists: the fleet-wide query_log scan is
        # terabytes. If the cache read regresses, the scan runs every warming run
        # again — this fails when the second run re-hits ClickHouse.
        mock_exec.return_value = [(101, '{"kind": "WebOverviewQuery"}', 50, 123)]

        first = get_warmable_queries_op(dagster.build_op_context())
        second = get_warmable_queries_op(dagster.build_op_context())

        self.assertEqual(mock_exec.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["team_id"], 101)

    @patch("products.web_analytics.dags.cache_warming.object_storage")
    @patch("products.web_analytics.dags.cache_warming.sync_execute")
    def test_storage_failure_falls_back_to_scan(self, mock_exec: MagicMock, mock_storage: MagicMock) -> None:
        # Object storage being unavailable must degrade to a fresh scan, not break warming.
        mock_storage.read_bytes.side_effect = Exception("storage unavailable")
        mock_exec.return_value = [(101, '{"kind": "WebOverviewQuery"}', 50, 123)]

        result = get_warmable_queries_op(dagster.build_op_context())

        self.assertEqual(len(result), 1)
        self.assertEqual(mock_exec.call_count, 1)


class TestWarmQueriesOp(BaseTest):
    @parameterized.expand(
        [
            # A raw-path (not lazy-eligible) shape below the pre-widening demand
            # bar must not replay: with the min-2 selection floor, two runs of an
            # expensive ineligible shape would otherwise become hourly background
            # scans outside the tenant's request throttles.
            ("raw_low_demand_skipped", False, 2, 0),
            ("raw_high_demand_warms", False, 10, 1),
            ("lazy_low_demand_warms", True, 2, 1),
        ]
    )
    def test_raw_replays_keep_higher_demand_bar(
        self, _name: str, lazy_eligible: bool, query_count: int, expected_runs: int
    ) -> None:
        runner = MagicMock()
        runner.get_cache_key.return_value = f"key-{_name}"
        with (
            patch(
                "products.web_analytics.dags.cache_warming.build_replay_runner",
                return_value=(runner, {}, lazy_eligible),
            ),
            patch("products.web_analytics.dags.cache_warming.DjangoCacheQueryCacheManager") as mock_cm,
        ):
            mock_cm.return_value.get_cache_data.return_value = None
            warm_queries_op(
                dagster.build_op_context(),
                [
                    {
                        "team_id": self.team.pk,
                        "query_json": {"kind": "WebOverviewQuery", "properties": []},
                        "query_count": query_count,
                        "normalized_query_hash": "h",
                    }
                ],
            )

        self.assertEqual(runner.run.call_count, expected_runs)

    def test_duplicate_cache_keys_warm_once(self) -> None:
        # Selection groups by raw JSON text, so two encodings of one query can
        # both be selected; replaying both wastes ClickHouse capacity and
        # double-counts warmed outcomes.
        runner = MagicMock()
        runner.get_cache_key.return_value = "same-key"
        with (
            patch("products.web_analytics.dags.cache_warming.build_replay_runner", return_value=(runner, {}, True)),
            patch("products.web_analytics.dags.cache_warming.DjangoCacheQueryCacheManager") as mock_cm,
        ):
            mock_cm.return_value.get_cache_data.return_value = None
            warm_queries_op(
                dagster.build_op_context(),
                [
                    {
                        "team_id": self.team.pk,
                        "query_json": {"kind": "WebOverviewQuery", "properties": []},
                        "normalized_query_hash": "a",
                    },
                    {
                        "team_id": self.team.pk,
                        "query_json": {"properties": [], "kind": "WebOverviewQuery"},
                        "normalized_query_hash": "b",
                    },
                ],
            )

        self.assertEqual(runner.run.call_count, 1)

    def test_reused_threads_do_not_leak_tags_between_shapes(self) -> None:
        # Pool threads are reused and tag_queries merges rather than replaces:
        # without the per-shape reset, tags a previous shape's runner added
        # (client_query_id here) bleed into the next shape's queries.
        leaked: list = []
        calls = {"n": 0}

        def fake_runner_or_none(**kwargs) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                tag_queries(client_query_id="polluted")
            else:
                leaked.append(get_query_tags().client_query_id)
            return None

        shape = {"team_id": self.team.pk, "query_json": {"kind": "WebOverviewQuery", "properties": []}}
        with (
            patch("products.web_analytics.dags.cache_warming.WARMING_SHAPE_CONCURRENCY", 1),
            patch(
                "products.web_analytics.dags.cache_warming.get_query_runner_or_none", side_effect=fake_runner_or_none
            ),
        ):
            warm_queries_op(
                dagster.build_op_context(),
                [{**shape, "normalized_query_hash": "a"}, {**shape, "normalized_query_hash": "b"}],
            )

        self.assertEqual(leaked, [None])

    def test_worker_threads_carry_warming_tags(self) -> None:
        # Query tags are thread-local. If tagging moves back to the op thread,
        # pool workers replay untagged and two things silently break: the lazy
        # gate's rollout bypass (buckets stop building for non-enrolled teams)
        # and the selection's self-feedback exclusion.
        seen: list[bool] = []

        def capture_tags(**kwargs) -> None:
            seen.append(is_background_warming_request())
            return None

        with patch("products.web_analytics.dags.cache_warming.get_query_runner_or_none", side_effect=capture_tags):
            warm_queries_op(
                dagster.build_op_context(),
                [
                    {
                        "team_id": self.team.pk,
                        "query_json": {"kind": "WebOverviewQuery", "properties": []},
                        "normalized_query_hash": "h",
                    }
                ],
            )

        self.assertEqual(seen, [True])

    @patch("products.web_analytics.dags.cache_warming.capture_exception")
    def test_kind_without_runner_is_not_an_error(self, mock_capture: MagicMock) -> None:
        # Selection is by kind prefix, so kinds get_query_runner can't build
        # (WebVitalsQuery) reach the warm op. They must be skipped quietly — as
        # "unsupported", not "failed" — or every hourly run pages Sentry.
        warm_queries_op(
            dagster.build_op_context(),
            [{"team_id": self.team.pk, "query_json": {"kind": "WebVitalsQuery"}, "normalized_query_hash": "h"}],
        )

        mock_capture.assert_not_called()
