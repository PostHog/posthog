from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

import dagster
from parameterized import parameterized

from products.web_analytics.dags.cache_warming import (
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

    @patch("products.web_analytics.dags.cache_warming.sync_execute", return_value=[])
    def test_op_reads_instance_settings(self, _mock_exec: MagicMock) -> None:
        # Runs the op against the real instance-setting machinery so a renamed or
        # unregistered setting key fails here instead of at the hourly run.
        result = get_warmable_queries_op(dagster.build_op_context())
        self.assertEqual(result, [])


class TestWarmQueriesOp(BaseTest):
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
