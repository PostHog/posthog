import gzip
import json
import threading
from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils.dateparse import parse_datetime

import dagster
from parameterized import parameterized

from posthog.clickhouse.query_tagging import Feature, get_query_tags, reset_query_tags, tag_queries
from posthog.exceptions import ClickHouseAtCapacity
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.query_cache import EntryFreshness

from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import is_background_warming_request
from products.web_analytics.dags import cache_warming
from products.web_analytics.dags.cache_warming import (
    WarmQueriesConfig,
    build_replay_runner,
    canonicalize_lazy_replay_json,
    deepen_to_widest_warmable_range,
    get_warmable_queries_op,
    maybe_expand_warming_date_range,
    maybe_opt_into_lazy_precompute,
    queries_to_keep_fresh,
    split_warmable_queries_op,
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


class TestDeepenToWidestWarmableRange(BaseTest):
    @parameterized.expand(
        [
            # Deepen to the widest exact range the shape's demand covers, so one
            # warm builds the buckets every narrower variant reuses.
            ("picks_deepest_day", "-7d", ["-7d", "-30d", "-90d"], 180, "-90d"),
            ("weeks_convert_to_days", "-7d", ["-7d", "-5w"], 180, "-5w"),  # 5w = 35d > 7d
            ("hours_are_shallow", "-90d", ["-90d", "-12h"], 180, "-90d"),  # 12h = 0d
            ("cap_boundary_is_inclusive", "-7d", ["-7d", "-180d"], 180, "-180d"),
            # Ranges past the cap can't be precomputed, so a warmable sibling must
            # win instead of an unwarmable deep one being picked and rejected.
            ("excludes_over_cap", "-7d", ["-7d", "-365d"], 180, "-7d"),
            ("picks_deepest_in_cap", "-7d", ["-7d", "-90d", "-365d"], 180, "-90d"),
            # Variable / point-in-time / unbounded forms have no monotonic depth,
            # so they never override a concrete range and are left untouched.
            ("skips_month_start", "-7d", ["-7d", "mStart"], 180, "-7d"),
            ("skips_absolute_and_all", "-14d", ["-14d", "all", "2026-01-01"], 180, "-14d"),
            ("no_exact_forms_is_noop", "mStart", ["mStart", "all"], 180, "mStart"),
            ("single_variant_is_noop", "-30d", ["-30d"], 180, "-30d"),
        ]
    )
    def test_deepening(
        self, _name: str, representative_from: str, observed: list[str], max_days: int, expected_from: str
    ) -> None:
        query = {
            "kind": "WebOverviewQuery",
            "useWebAnalyticsPrecompute": True,
            "dateRange": {"date_from": representative_from},
        }

        result = deepen_to_widest_warmable_range(query, observed, max_days)

        self.assertEqual(result["dateRange"]["date_from"], expected_from)

    @parameterized.expand(
        [
            # Deepening is confined to the lazy path and open-ended ranges, so each
            # of these must ignore the deeper -90d sibling. Opted-out and non-lazy
            # shapes replay raw — a deeper scan there is background load the tenant
            # never ran, counted only at the shallow variant. A fixed date_to can't
            # be paired with another variant's date_from (normalization dropped
            # which endpoints went together), so splicing -90d onto it could
            # reverse or balloon the span.
            (
                "opted_out",
                {"kind": "WebOverviewQuery", "useWebAnalyticsPrecompute": False, "dateRange": {"date_from": "-7d"}},
            ),
            (
                "non_lazy_kind",
                {
                    "kind": "WebExternalClicksTableQuery",
                    "useWebAnalyticsPrecompute": True,
                    "dateRange": {"date_from": "-7d"},
                },
            ),
            (
                "explicit_date_to",
                {
                    "kind": "WebOverviewQuery",
                    "useWebAnalyticsPrecompute": True,
                    "dateRange": {"date_from": "-7d", "date_to": "-1d"},
                },
            ),
        ]
    )
    def test_leaves_non_lazy_or_bounded_ranges_untouched(self, _name: str, query: dict) -> None:
        self.assertIs(deepen_to_widest_warmable_range(query, ["-7d", "-90d"], 180), query)


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

    @parameterized.expand(
        [
            # No deep demand: a sub-30d shape widens to the standard warm depth.
            ("no_deep_demand_widens_to_30d", [], "-30d"),
            # Deep demand: the replay deepens to the widest range the shape needs,
            # past the -30d default — so one warm covers the -90d variant too.
            ("deep_demand_deepens", ["-7d", "-90d"], "-90d"),
        ]
    )
    def test_lazy_eligible_shape_range(self, _name: str, observed: list[str], expected_from: str) -> None:
        # Under the warming tag even a non-enrolled team widens: building
        # buckets for not-yet-enrolled teams is the warmer's purpose.
        query = {
            "kind": "WebOverviewQuery",
            "properties": [],
            "useWebAnalyticsPrecompute": True,
            "dateRange": {"date_from": "-7d"},
        }

        runner, used_json, lazy_eligible = build_replay_runner(self.team, query, observed)

        self.assertIsNotNone(runner)
        self.assertTrue(lazy_eligible)
        self.assertEqual(used_json["dateRange"]["date_from"], expected_from)

    @parameterized.expand(
        [
            # Shapes every lazy family rejects execute on the raw path — a deepened
            # or widened replay there is a scan the tenant never ran, outside their
            # request throttles. The deep -90d demand below must NOT be adopted:
            # its count belongs to the shallow variant, and the raw guard would let
            # it through, so an ineligible shape would replay a 90-day scan hourly.
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

        runner, used_json, lazy_eligible = build_replay_runner(self.team, query, ["-7d", "-90d"])

        self.assertIsNotNone(runner)
        self.assertFalse(lazy_eligible)
        self.assertEqual(used_json["dateRange"]["date_from"], "-7d")

    @parameterized.expand(
        [
            # The shared gate rejects both shapes as submitted; canonicalizing
            # before the check would erase the rejection (drop the modifier,
            # step the over-cap lookback under MAX_PRECOMPUTE_DAYS) and build
            # buckets the shape's real queries can never consume, held only to
            # the lazy demand floor instead of the raw one.
            ("uuid_join_mode", {"modifiers": {"sessionsV2JoinMode": "uuid"}}, ["-7d"], "-7d"),
            ("only_over_cap_demand", {"dateRange": {"date_from": "-180d"}}, ["-180d"], "-180d"),
        ]
    )
    def test_ineligible_shape_is_not_canonicalized_into_eligibility(
        self, _name: str, extra: dict, observed: list[str], expected_from: str
    ) -> None:
        query = {
            "kind": "WebOverviewQuery",
            "properties": [],
            "useWebAnalyticsPrecompute": True,
            "dateRange": {"date_from": "-7d"},
            **extra,
        }

        runner, used_json, lazy_eligible = build_replay_runner(self.team, query, observed)

        self.assertIsNotNone(runner)
        self.assertFalse(lazy_eligible)
        self.assertEqual(used_json["dateRange"]["date_from"], expected_from)
        self.assertEqual(used_json, query)

    def test_outside_warming_context_gate_fails_closed(self) -> None:
        reset_query_tags()
        query = {
            "kind": "WebOverviewQuery",
            "properties": [],
            "useWebAnalyticsPrecompute": True,
            "dateRange": {"date_from": "-7d"},
        }

        runner, used_json, lazy_eligible = build_replay_runner(self.team, query, [])

        self.assertIsNotNone(runner)
        self.assertFalse(lazy_eligible)
        self.assertEqual(used_json["dateRange"]["date_from"], "-7d")

    @parameterized.expand(
        [
            # A snapshot rotation that flips the representative to a sibling
            # variant — compare toggled, a different sub-30d preset — must not
            # rotate the staleness cache key; before canonicalization every such
            # flip re-warmed the shape even though its buckets were fresh.
            (
                "overview_compare_and_preset_variant",
                {"kind": "WebOverviewQuery", "properties": []},
                {"dateRange": {"date_from": "wStart"}, "compareFilter": {"compare": True}},
            ),
            (
                "stats_limit_variant",
                {"kind": "WebStatsTableQuery", "properties": [], "breakdownBy": "Browser"},
                {"dateRange": {"date_from": "dStart"}, "limit": 50},
            ),
        ]
    )
    def test_representative_variants_share_one_cache_key(self, _name: str, shape: dict, variant_extra: dict) -> None:
        base = {**shape, "useWebAnalyticsPrecompute": True, "dateRange": {"date_from": "-7d"}}
        variant = {**base, **variant_extra}

        base_runner, _, base_eligible = build_replay_runner(self.team, base, ["-7d"])
        variant_runner, _, variant_eligible = build_replay_runner(self.team, variant, ["-7d"])

        assert base_runner is not None and variant_runner is not None
        self.assertTrue(base_eligible)
        self.assertTrue(variant_eligible)
        self.assertEqual(base_runner.get_cache_key(), variant_runner.get_cache_key())


class TestCanonicalizeLazyReplay(BaseTest):
    @parameterized.expand(
        [
            ("steps_up_to_next_multiple", "-31d", "-45d"),
            ("on_step_unchanged", "-45d", "-45d"),
            ("weeks_convert_then_step", "-6w", "-45d"),
            # 721h is just over 30 days; flooring to -30d would leave the
            # oldest partial day of the real request's span cold.
            ("hours_round_up", "-721h", "-45d"),
            ("cap_holds", "-90d", "-90d"),
        ]
    )
    def test_lookback_steps(self, _name: str, date_from: str, expected: str) -> None:
        query = {
            "kind": "WebOverviewQuery",
            "useWebAnalyticsPrecompute": True,
            "dateRange": {"date_from": date_from},
        }

        self.assertEqual(canonicalize_lazy_replay_json(query)["dateRange"]["date_from"], expected)

    def test_variant_fields_dropped_shape_fields_kept(self) -> None:
        query = {
            "kind": "WebStatsTableQuery",
            "useWebAnalyticsPrecompute": True,
            "properties": [{"key": "$host", "value": "posthog.com", "type": "event"}],
            "breakdownBy": "Browser",
            "filterTestAccounts": True,
            "dateRange": {"date_from": "-30d"},
            "compareFilter": {"compare": True},
            "limit": 50,
            "modifiers": {"sessionTableVersion": "v2"},
            "version": 2,
        }

        canonical = canonicalize_lazy_replay_json(query)

        for dropped in ("compareFilter", "limit", "modifiers", "version"):
            self.assertNotIn(dropped, canonical)
        self.assertEqual(canonical["properties"], query["properties"])
        self.assertEqual(canonical["breakdownBy"], "Browser")
        self.assertIs(canonical["filterTestAccounts"], True)
        self.assertIs(canonical["useWebAnalyticsPrecompute"], True)

    @parameterized.expand(
        [
            (
                "non_lazy_kind",
                {"kind": "WebExternalClicksTableQuery", "useWebAnalyticsPrecompute": True, "compareFilter": {}},
            ),
            ("opted_out", {"kind": "WebOverviewQuery", "useWebAnalyticsPrecompute": False, "compareFilter": {}}),
        ]
    )
    def test_off_lazy_path_is_untouched(self, _name: str, query: dict) -> None:
        self.assertIs(canonicalize_lazy_replay_json(query), query)

    @parameterized.expand(
        [
            # A bounded span keeps its faithful range for the same reason
            # deepening skips it, and non-exact forms have no monotonic depth
            # to step — both still shed the variant fields.
            ("bounded_range", {"date_from": "-7d", "date_to": "-1d"}),
            ("month_start", {"date_from": "mStart"}),
        ]
    )
    def test_unsteppable_ranges_keep_span_but_shed_variant_fields(self, _name: str, date_range: dict) -> None:
        query = {
            "kind": "WebOverviewQuery",
            "useWebAnalyticsPrecompute": True,
            "dateRange": date_range,
            "compareFilter": {"compare": True},
        }

        canonical = canonicalize_lazy_replay_json(query)

        self.assertEqual(canonical["dateRange"], date_range)
        self.assertNotIn("compareFilter", canonical)


class TestSplitWarmableQueries(BaseTest):
    def _shape(self, team_id: int, n: int) -> dict:
        return {
            "team_id": team_id,
            "query_json": {"kind": "WebOverviewQuery", "n": n},
            "query_count": 5,
            "representative_query_count": 5,
            "normalized_query_hash": f"h{n}",
        }

    def test_shards_are_team_disjoint_and_lossless(self) -> None:
        # A team split across shards breaks the per-shard (team, cache_key)
        # dedupe and warms duplicates; a dropped or duplicated shape silently
        # under- or over-warms. Both fail here.
        queries = [self._shape(team, n) for n, team in enumerate([1, 2, 3, 9, 10, 17, 2, 9, 1])]

        outputs = list(split_warmable_queries_op(dagster.build_op_context(), WarmQueriesConfig(), queries))

        team_to_shard: dict[int, str] = {}
        seen_hashes = []
        for out in outputs:
            for q in out.value["queries"]:
                seen_hashes.append(q["normalized_query_hash"])
                previously = team_to_shard.setdefault(q["team_id"], out.mapping_key)
                self.assertEqual(previously, out.mapping_key)
        self.assertEqual(sorted(seen_hashes), sorted(q["normalized_query_hash"] for q in queries))

    def test_scoping_applies_before_sharding(self) -> None:
        # team_ids/limit moved from the warm op to the split — if they stop
        # applying, a scoped Launchpad launch warms the whole fleet while
        # holding the schedule's slot.
        queries = [self._shape(team, n) for n, team in enumerate([1, 2, 1, 3, 1])]

        outputs = list(
            split_warmable_queries_op(
                dagster.build_op_context(), WarmQueriesConfig(mode="backfill", team_ids=[1], limit=2), queries
            )
        )

        shapes = [q for out in outputs for q in out.value["queries"]]
        self.assertEqual(len(shapes), 2)
        self.assertTrue(all(q["team_id"] == 1 for q in shapes))
        self.assertTrue(all(out.value["mode"] == "backfill" for out in outputs))

    def test_unknown_mode_fails_before_fanout(self) -> None:
        with self.assertRaises(ValueError):
            list(split_warmable_queries_op(dagster.build_op_context(), WarmQueriesConfig(mode="bogus"), []))


class TestFleetQuerySelection(BaseTest):
    @patch("products.web_analytics.dags.cache_warming.sync_execute")
    def test_parses_fleet_rows_into_query_infos(self, mock_exec: MagicMock) -> None:
        # Guards the row-shape contract with the selection SQL: the summed and
        # representative counts are distinct columns (the raw guard keys on the
        # representative, so they must not be swapped), and observed_date_froms is
        # carried through untouched for build_replay_runner to deepen later — the
        # selection output keeps each shape's faithful representative range. A
        # column reorder or dropped column fails here.
        mock_exec.return_value = [
            (101, '{"kind": "WebOverviewQuery", "dateRange": {"date_from": "-7d"}}', 50, 8, "hash-a", ["-7d", "-90d"]),
            (202, '{"kind": "WebStatsTableQuery"}', 12, 12, "hash-b", ["mStart"]),
        ]
        result = queries_to_keep_fresh(dagster.build_op_context(), days=7, minimum_query_count=10, max_shapes=100)

        self.assertEqual(
            result,
            [
                {
                    "team_id": 101,
                    "query_json": {"kind": "WebOverviewQuery", "dateRange": {"date_from": "-7d"}},
                    "query_count": 50,
                    "representative_query_count": 8,
                    "normalized_query_hash": "hash-a",
                    "observed_date_froms": ["-7d", "-90d"],
                },
                {
                    "team_id": 202,
                    "query_json": {"kind": "WebStatsTableQuery"},
                    "query_count": 12,
                    "representative_query_count": 12,
                    "normalized_query_hash": "hash-b",
                    "observed_date_froms": ["mStart"],
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
        mock_exec.return_value = [(101, '{"kind": "WebOverviewQuery"}', 50, 50, 123, ["-7d"])]

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
        mock_exec.return_value = [(101, '{"kind": "WebOverviewQuery"}', 50, 50, 123, ["-7d"])]

        result = get_warmable_queries_op(dagster.build_op_context())

        self.assertEqual(len(result), 1)
        self.assertEqual(mock_exec.call_count, 1)

    @patch("products.web_analytics.dags.cache_warming.object_storage")
    @patch("products.web_analytics.dags.cache_warming.sync_execute")
    def test_malformed_cache_payload_falls_back_to_scan(self, mock_exec: MagicMock, mock_storage: MagicMock) -> None:
        # A decodable-but-malformed blob (missing the expected fields) must miss
        # and trigger a fresh scan, not raise out of the op and skip warming.
        mock_storage.read_bytes.return_value = gzip.compress(json.dumps({"unexpected": "shape"}).encode())
        mock_exec.return_value = [(101, '{"kind": "WebOverviewQuery"}', 50, 50, 123, ["-7d"])]

        result = get_warmable_queries_op(dagster.build_op_context())

        self.assertEqual(len(result), 1)
        self.assertEqual(mock_exec.call_count, 1)


class TestWarmQueriesOp(BaseTest):
    @parameterized.expand(
        [
            # A raw-path (not lazy-eligible) shape below the demand bar must not
            # replay: an expensive ineligible shape would otherwise become an
            # hourly background scan outside the tenant's request throttles.
            ("raw_low_demand_skipped", False, 2, 0),
            ("raw_high_demand_warms", False, 10, 1),
            ("lazy_low_demand_warms", True, 2, 1),
        ]
    )
    def test_raw_replays_keep_higher_demand_bar(
        self, _name: str, lazy_eligible: bool, representative_query_count: int, expected_runs: int
    ) -> None:
        runner = MagicMock()
        runner.get_cache_key.return_value = f"key-{_name}"
        with (
            patch(
                "products.web_analytics.dags.cache_warming.build_replay_runner",
                return_value=(runner, {}, lazy_eligible),
            ),
            patch("products.web_analytics.dags.cache_warming.QueryCache") as mock_cm,
        ):
            mock_cm.return_value.freshness.return_value = None
            warm_queries_op(
                dagster.build_op_context(),
                WarmQueriesConfig(),
                [
                    {
                        "team_id": self.team.pk,
                        "query_json": {"kind": "WebOverviewQuery", "properties": []},
                        # Shape-wide sum is deliberately high: the raw guard must
                        # read the representative's own count, so a high sum can't
                        # promote a rarely-run expensive variant.
                        "query_count": 999,
                        "representative_query_count": representative_query_count,
                        "normalized_query_hash": "h",
                    }
                ],
            )

        self.assertEqual(runner.run.call_count, expected_runs)

    @parameterized.expand(
        [
            # The dagster CH user's simultaneous-query cap is shared with other
            # Dagster jobs, so co-tenant bursts hit the warmer as AtCapacity for
            # a few seconds. A transient burst must be retried (deferring every
            # affected shape a whole hour), while sustained
            # saturation must still fail after the bounded retries — unbounded
            # retrying would wedge every worker thread against a hard cap.
            ("transient_202_recovers", [ClickHouseAtCapacity(), None], 2, False),
            (
                "persistent_202_fails",
                [ClickHouseAtCapacity(), ClickHouseAtCapacity(), ClickHouseAtCapacity()],
                3,
                True,
            ),
        ]
    )
    def test_at_capacity_retries_bounded(
        self, _name: str, run_side_effect: list, expected_runs: int, expect_failure: bool
    ) -> None:
        runner = MagicMock()
        runner.get_cache_key.return_value = f"key-{_name}"
        runner.run.side_effect = run_side_effect
        with (
            patch(
                "products.web_analytics.dags.cache_warming.build_replay_runner",
                return_value=(runner, {}, True),
            ),
            patch("products.web_analytics.dags.cache_warming.QueryCache") as mock_cm,
            patch("products.web_analytics.dags.cache_warming.time.sleep") as mock_sleep,
            patch("products.web_analytics.dags.cache_warming.capture_exception") as mock_capture,
        ):
            mock_cm.return_value.freshness.return_value = None
            warm_queries_op(
                dagster.build_op_context(),
                WarmQueriesConfig(),
                [
                    {
                        "team_id": self.team.pk,
                        "query_json": {"kind": "WebOverviewQuery", "properties": []},
                        "query_count": 10,
                        "representative_query_count": 10,
                        "normalized_query_hash": "h",
                    }
                ],
            )

        self.assertEqual(runner.run.call_count, expected_runs)
        self.assertEqual(mock_sleep.call_count, expected_runs - 1)
        self.assertEqual(mock_capture.called, expect_failure)

    @parameterized.expand(
        [
            # A churned team surfaces as a DoesNotExist from get_cache_key (the
            # team-extension FK). That must be a quiet skip, not a logged failure
            # plus an error-tracking event per churned team — which spammed
            # tracebacks in prod. But DoesNotExist alone isn't proof the team is
            # gone — other models raise it too (a cohort filter whose cohort was
            # deleted) — so for a live team it must still report, as must any
            # other error.
            ("churned_team_does_not_exist", Team.DoesNotExist, False, 0),
            ("live_team_other_model_does_not_exist", Team.DoesNotExist, True, 1),
            ("genuine_failure", RuntimeError, True, 1),
        ]
    )
    def test_churned_team_skipped_but_real_failure_reported(
        self, _name: str, raised: type[Exception], team_exists: bool, expected_capture_calls: int
    ) -> None:
        runner = MagicMock()
        runner.get_cache_key.side_effect = raised("boom")
        with (
            patch(
                "products.web_analytics.dags.cache_warming.build_replay_runner",
                return_value=(runner, {}, True),
            ),
            patch("products.web_analytics.dags.cache_warming.capture_exception") as mock_capture,
            # Pinned because pool worker threads hold their own DB connections and
            # can't see this TestCase's uncommitted team row.
            patch("products.web_analytics.dags.cache_warming._team_still_exists", return_value=team_exists),
        ):
            warm_queries_op(
                dagster.build_op_context(),
                WarmQueriesConfig(),
                [
                    {
                        "team_id": self.team.pk,
                        "query_json": {"kind": "WebOverviewQuery", "properties": []},
                        "query_count": 5,
                        "representative_query_count": 5,
                        "normalized_query_hash": "h",
                    }
                ],
            )

        self.assertEqual(mock_capture.call_count, expected_capture_calls)
        self.assertEqual(runner.run.call_count, 0)

    @parameterized.expand(
        [
            # Mode gates on the cache entry (warm/cold discriminator). Inverting
            # either condition is a real operational hazard: backfill re-running
            # the warm set repeats the hours-long cold rebuild the mode exists to
            # avoid, and refresh cold-building defeats its cheap-pass purpose.
            ("full_runs_cold", "full", False, 1),
            ("refresh_skips_cold", "refresh", False, 0),
            ("refresh_runs_warm_stale", "refresh", True, 1),
            ("backfill_runs_cold", "backfill", False, 1),
            ("backfill_skips_warm", "backfill", True, 0),
        ]
    )
    def test_mode_gates_on_warm_state(self, _name: str, mode: str, has_entry: bool, expected_runs: int) -> None:
        runner = MagicMock()
        runner.get_cache_key.return_value = f"key-{_name}"
        runner._is_stale.return_value = True
        with (
            patch("products.web_analytics.dags.cache_warming.build_replay_runner", return_value=(runner, {}, True)),
            patch("products.web_analytics.dags.cache_warming.QueryCache") as mock_cm,
        ):
            freshness = EntryFreshness(last_refresh="2026-07-01T00:00:00Z") if has_entry else None
            mock_cm.return_value.freshness.return_value = freshness
            warm_queries_op(
                dagster.build_op_context(),
                WarmQueriesConfig(mode=mode),
                [
                    {
                        "team_id": self.team.pk,
                        "query_json": {"kind": "WebOverviewQuery", "properties": []},
                        "query_count": 5,
                        "representative_query_count": 5,
                        "normalized_query_hash": "h",
                    }
                ],
            )

        self.assertEqual(runner.run.call_count, expected_runs)

    @parameterized.expand(
        [
            # A dead ClickHouse node can block every pool thread in a socket
            # read forever: nothing completes, the run wedges, and mutual
            # exclusion starves every later scheduled tick (observed in prod as
            # a silent pod needing manual termination). With queued work beyond
            # the in-flight set the pass must hard-exit so Dagster records a
            # failure and the next tick recovers. A quiet tail with only the
            # in-flight remainder pending is a legitimate slow straggler and
            # must NOT exit.
            # One silent window with queued work is definitive; a quiet tail
            # gets WARMING_TAIL_STALL_WINDOWS before the same verdict — a
            # single slow straggler survives, a fully wedged tail cannot spin
            # forever (greptile P1: the old tail branch looped indefinitely).
            ("stall_with_queued_work_exits", 10, 1, True),
            ("slow_tail_one_window_keeps_waiting", 3, 1, False),
            ("wedged_tail_exits_after_windows", 3, cache_warming.WARMING_TAIL_STALL_WINDOWS, True),
        ]
    )
    def test_stalled_pass_fails_fast_instead_of_wedging(
        self, _name: str, n_shapes: int, empty_windows: int, expect_exit: bool
    ) -> None:
        class _Exited(BaseException):
            pass

        runner = MagicMock()
        runner.get_cache_key.side_effect = lambda: f"key-{runner.get_cache_key.call_count}"
        real_wait = cache_warming.wait
        calls = {"n": 0}

        def fake_wait(
            pending: set, timeout: float | None = None, return_when: str = "ALL_COMPLETED"
        ) -> tuple[set, set]:
            calls["n"] += 1
            if calls["n"] <= empty_windows:
                return set(), pending
            return real_wait(pending, timeout=5, return_when=return_when)

        with (
            patch("products.web_analytics.dags.cache_warming.build_replay_runner", return_value=(runner, {}, True)),
            patch("products.web_analytics.dags.cache_warming.QueryCache") as mock_cm,
            patch("products.web_analytics.dags.cache_warming.wait", side_effect=fake_wait),
            patch("products.web_analytics.dags.cache_warming.os._exit", side_effect=_Exited) as mock_exit,
        ):
            mock_cm.return_value.freshness.return_value = None
            shapes = [
                {
                    "team_id": self.team.pk,
                    "query_json": {"kind": "WebOverviewQuery", "properties": [], "n": i},
                    "query_count": 5,
                    "representative_query_count": 5,
                    "normalized_query_hash": f"h{i}",
                }
                for i in range(n_shapes)
            ]
            if expect_exit:
                with self.assertRaises(_Exited):
                    warm_queries_op(dagster.build_op_context(), WarmQueriesConfig(), shapes)
            else:
                warm_queries_op(dagster.build_op_context(), WarmQueriesConfig(), shapes)

        self.assertEqual(mock_exit.called, expect_exit)
        if not expect_exit:
            self.assertEqual(runner.run.call_count, n_shapes)

    def test_crawling_pass_fails_at_deadline(self) -> None:
        # A pass that completes one shape per stall window never trips the
        # no-progress guard, but crawling like that holds the job's single run
        # slot indefinitely and blocks every scheduled tick. It must fail at
        # the pass deadline via a clean dagster.Failure (in-flight shapes are
        # healthy, so no hard exit).
        class _Exited(BaseException):
            pass

        runner = MagicMock()
        runner.get_cache_key.side_effect = lambda: f"key-{runner.get_cache_key.call_count}"
        real_wait = cache_warming.wait
        fake_time = SimpleNamespace(now=0.0)
        fake_time.monotonic = lambda: fake_time.now
        fake_time.sleep = lambda _s: None
        wait_timeouts: list[float | None] = []

        def fake_wait(
            pending: set, timeout: float | None = None, return_when: str = "ALL_COMPLETED"
        ) -> tuple[set, set]:
            wait_timeouts.append(timeout)
            fake_time.now += 10000.0
            first = next(iter(pending))
            real_wait({first}, timeout=5)
            return {first}, pending - {first}

        with (
            patch("products.web_analytics.dags.cache_warming.build_replay_runner", return_value=(runner, {}, True)),
            patch("products.web_analytics.dags.cache_warming.QueryCache") as mock_cm,
            patch("products.web_analytics.dags.cache_warming.wait", side_effect=fake_wait),
            patch("products.web_analytics.dags.cache_warming.time", new=fake_time),
            patch("products.web_analytics.dags.cache_warming.os._exit", side_effect=_Exited) as mock_exit,
        ):
            mock_cm.return_value.freshness.return_value = None
            shapes = [
                {
                    "team_id": self.team.pk,
                    "query_json": {"kind": "WebOverviewQuery", "properties": [], "n": i},
                    "query_count": 5,
                    "representative_query_count": 5,
                    "normalized_query_hash": f"h{i}",
                }
                for i in range(3)
            ]
            with self.assertRaises(dagster.Failure) as raised:
                warm_queries_op(dagster.build_op_context(), WarmQueriesConfig(), shapes)

        self.assertFalse(mock_exit.called)
        # Retrying would reset the deadline clock and hold the schedule slot
        # for another full deadline per attempt.
        self.assertIs(raised.exception.allow_retries, False)
        # The wait is truncated to the remaining deadline (second window has
        # only 800s left of the 10800s budget), so a quiet window cannot
        # overshoot the deadline by a full stall timeout.
        self.assertEqual(wait_timeouts[0], cache_warming.WARMING_STALL_TIMEOUT_SECONDS)
        self.assertEqual(wait_timeouts[1], 800.0)

    def test_staleness_evaluated_on_jitter_aged_entry(self) -> None:
        # Shapes warmed together go stale together (fixed threshold), so a bulk
        # pass turns into a synchronized expiry storm hours later. The warmer
        # must evaluate staleness on the entry aged by the shape's deterministic
        # offset — warming early diffuses the cohort. If the jitter is dropped,
        # a boundary-fresh entry skips instead of warming and storms return.
        runner = MagicMock()
        runner.get_cache_key.return_value = "key-jitter"
        real_last_refresh = parse_datetime("2026-07-01T00:00:00Z")
        # Stale only if judged on a timestamp older than the true one, i.e.
        # exactly when the jitter aged it.
        runner._is_stale.side_effect = lambda last_refresh: last_refresh < real_last_refresh
        with (
            patch("products.web_analytics.dags.cache_warming.build_replay_runner", return_value=(runner, {}, True)),
            patch("products.web_analytics.dags.cache_warming.QueryCache") as mock_cm,
        ):
            mock_cm.return_value.freshness.return_value = EntryFreshness(last_refresh="2026-07-01T00:00:00Z")
            warm_queries_op(
                dagster.build_op_context(),
                WarmQueriesConfig(),
                [
                    {
                        "team_id": self.team.pk,
                        "query_json": {"kind": "WebOverviewQuery", "properties": []},
                        "query_count": 5,
                        "representative_query_count": 5,
                        # crc32("h") % 3600 is nonzero, so the aged timestamp is
                        # strictly older than the true one.
                        "normalized_query_hash": "h",
                    }
                ],
            )

        self.assertEqual(runner.run.call_count, 1)
        # Forcing matters: run()'s default mode re-checks staleness against the
        # true last_refresh and would return the fresh cached response, turning
        # the early warm into a silent no-op.
        self.assertEqual(runner.run.call_args.kwargs.get("execution_mode"), ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

    def test_cancellation_drains_or_exits_within_grace(self) -> None:
        # Cancellation mid-pass must not hand the executor a queue to drain nor
        # hang joining a wedged thread (codex/greptile P1: the with-block exit
        # called shutdown(wait=True) after cancel_futures). Healthy in-flight
        # shapes finish within the grace and the interrupt propagates; wedged
        # ones trigger the hard exit.
        class _Exited(BaseException):
            pass

        release = threading.Event()
        runner = MagicMock()
        runner.get_cache_key.side_effect = lambda: f"key-{runner.get_cache_key.call_count}"
        runner.run.side_effect = lambda **kwargs: release.wait(10)

        real_wait = cache_warming.wait
        calls = {"n": 0}

        def interrupting_wait(pending: set, timeout: float | None = None, return_when: str = "") -> tuple[set, set]:
            calls["n"] += 1
            if calls["n"] == 1 and return_when:
                raise KeyboardInterrupt()
            # The grace-period wait (no return_when) runs for real, shortened.
            return real_wait(pending, timeout=0.2)

        try:
            with (
                patch(
                    "products.web_analytics.dags.cache_warming.build_replay_runner",
                    return_value=(runner, {}, True),
                ),
                patch("products.web_analytics.dags.cache_warming.QueryCache") as mock_cm,
                patch("products.web_analytics.dags.cache_warming.wait", side_effect=interrupting_wait),
                patch("products.web_analytics.dags.cache_warming.os._exit", side_effect=_Exited) as mock_exit,
            ):
                mock_cm.return_value.freshness.return_value = None
                with self.assertRaises(_Exited):
                    warm_queries_op(
                        dagster.build_op_context(),
                        WarmQueriesConfig(),
                        [
                            {
                                "team_id": self.team.pk,
                                "query_json": {"kind": "WebOverviewQuery", "properties": []},
                                "query_count": 5,
                                "representative_query_count": 5,
                                "normalized_query_hash": "h",
                            }
                        ],
                    )
                assert mock_exit.called
        finally:
            release.set()

    def test_team_ids_and_limit_scope_the_run(self) -> None:
        # A Launchpad run scoped to one team must not warm the fleet: launches
        # are mutually exclusive with the hourly schedule, so an unscoped manual
        # run starves it for the duration.
        other_team = Team.objects.create(organization=self.organization, name="other")
        runner = MagicMock()
        runner.get_cache_key.side_effect = lambda: f"key-{len(runner.mock_calls)}"
        shape = lambda team_id, n: {  # noqa: E731
            "team_id": team_id,
            "query_json": {"kind": "WebOverviewQuery", "properties": [], "n": n},
            "query_count": 5,
            "representative_query_count": 5,
            "normalized_query_hash": f"h{n}",
        }
        with (
            patch("products.web_analytics.dags.cache_warming.build_replay_runner", return_value=(runner, {}, True)),
            patch("products.web_analytics.dags.cache_warming.QueryCache") as mock_cm,
        ):
            mock_cm.return_value.freshness.return_value = None
            warm_queries_op(
                dagster.build_op_context(),
                WarmQueriesConfig(team_ids=[self.team.pk], limit=2),
                [shape(self.team.pk, 1), shape(other_team.pk, 2), shape(self.team.pk, 3), shape(self.team.pk, 4)],
            )

        # 3 shapes match the team filter; limit=2 caps it.
        self.assertEqual(runner.run.call_count, 2)

    def test_duplicate_cache_keys_warm_once(self) -> None:
        # Selection groups by raw JSON text, so two encodings of one query can
        # both be selected; replaying both wastes ClickHouse capacity and
        # double-counts warmed outcomes.
        runner = MagicMock()
        runner.get_cache_key.return_value = "same-key"
        with (
            patch("products.web_analytics.dags.cache_warming.build_replay_runner", return_value=(runner, {}, True)),
            patch("products.web_analytics.dags.cache_warming.QueryCache") as mock_cm,
        ):
            mock_cm.return_value.freshness.return_value = None
            warm_queries_op(
                dagster.build_op_context(),
                WarmQueriesConfig(),
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
            patch("products.web_analytics.dags.cache_warming.WARMING_SHARD_THREADS", 1),
            patch(
                "products.web_analytics.dags.cache_warming.get_query_runner_or_none", side_effect=fake_runner_or_none
            ),
        ):
            warm_queries_op(
                dagster.build_op_context(),
                WarmQueriesConfig(),
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
                WarmQueriesConfig(),
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
            WarmQueriesConfig(),
            [{"team_id": self.team.pk, "query_json": {"kind": "WebVitalsQuery"}, "normalized_query_hash": "h"}],
        )

        mock_capture.assert_not_called()
