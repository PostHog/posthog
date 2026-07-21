from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

import dagster
from parameterized import parameterized

from products.web_analytics.dags.cache_warming import (
    get_warmable_queries_op,
    maybe_opt_into_lazy_precompute,
    queries_to_keep_fresh,
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
    def test_op_reads_instance_settings(self, _mock_exec: MagicMock) -> None:
        # Runs the op against the real instance-setting machinery so a renamed or
        # unregistered setting key fails here instead of at the hourly run.
        result = get_warmable_queries_op(dagster.build_op_context())
        self.assertEqual(result, [])
