from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

import dagster
from parameterized import parameterized

from products.web_analytics.dags.cache_warming import (
    get_active_web_analytics_team_ids,
    get_teams_for_warming_op,
    maybe_opt_into_lazy_precompute,
)


class TestMaybeOptIntoLazyPrecompute(BaseTest):
    def test_enrolled_team_web_query_gets_opt_in(self) -> None:
        # If this breaks, warming an enrolled-but-restricted team silently stops
        # computing its lazy jobs — the pre-enrollment evaluation pipeline reads empty.
        query = {"kind": "WebStatsTableQuery", "properties": []}
        with self.settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=[self.team.id]):
            result = maybe_opt_into_lazy_precompute(self.team, query)

        self.assertIs(result["useWebAnalyticsPrecompute"], True)
        self.assertNotIn("useWebAnalyticsPrecompute", query)  # input not mutated

    @parameterized.expand(
        [
            # Non-web kinds don't carry the field; injecting it would break validation.
            ("non_web_kind", {"kind": "TrendsQuery"}, True),
            # Teams outside the enrollment lists must warm exactly what users run.
            ("not_enrolled", {"kind": "WebStatsTableQuery"}, False),
            # An explicit user opt-out in the replayed shape is preserved.
            ("explicit_opt_out", {"kind": "WebStatsTableQuery", "useWebAnalyticsPrecompute": False}, True),
        ]
    )
    def test_leaves_query_untouched(self, _name: str, query: dict, enrolled: bool) -> None:
        team_ids = [self.team.id] if enrolled else []
        with self.settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=team_ids):
            result = maybe_opt_into_lazy_precompute(self.team, query)

        self.assertEqual(result, query)


class TestActiveWebAnalyticsTeamIds(BaseTest):
    @patch("products.web_analytics.dags.cache_warming.sync_execute")
    def test_zero_limit_skips_clickhouse(self, mock_exec: MagicMock) -> None:
        # Ramp knob off (the default) must not run a fleet-wide query_log scan every hour.
        self.assertEqual(get_active_web_analytics_team_ids(0), [])
        mock_exec.assert_not_called()

    @patch("products.web_analytics.dags.cache_warming.sync_execute")
    def test_returns_ranked_team_ids(self, mock_exec: MagicMock) -> None:
        mock_exec.return_value = [(101, 50), (202, 20)]
        self.assertEqual(get_active_web_analytics_team_ids(5), [101, 202])

    @patch("products.web_analytics.dags.cache_warming.sync_execute", side_effect=Exception("clickhouse down"))
    def test_clickhouse_failure_falls_back_to_empty(self, _mock_exec: MagicMock) -> None:
        # Best-effort: a CH blip must fall back to the static list, not skip the whole run.
        self.assertEqual(get_active_web_analytics_team_ids(5), [])


class TestWarmingAudience(BaseTest):
    @patch("products.web_analytics.dags.cache_warming.sync_execute")
    @patch("products.web_analytics.dags.cache_warming.get_instance_setting")
    def test_unions_static_and_active_deduped_static_first(self, mock_setting: MagicMock, mock_exec: MagicMock) -> None:
        # A team present in both the static list and the active audience must warm
        # once (not twice), and static teams come first so a truncated run covers them.
        mock_setting.side_effect = lambda key: {
            "WEB_ANALYTICS_WARMING_TEAMS_TO_WARM": [2, 7],
            "WEB_ANALYTICS_WARMING_MAX_ACTIVE_TEAMS": 3,
        }[key]
        mock_exec.return_value = [(7, 50), (9, 20)]  # team 7 overlaps the static list

        result = get_teams_for_warming_op(dagster.build_op_context(), MagicMock())

        self.assertEqual(result, [2, 7, 9])

    @patch("products.web_analytics.dags.cache_warming.sync_execute")
    @patch("products.web_analytics.dags.cache_warming.get_instance_setting")
    def test_disabled_ramp_returns_only_static(self, mock_setting: MagicMock, mock_exec: MagicMock) -> None:
        mock_setting.side_effect = lambda key: {
            "WEB_ANALYTICS_WARMING_TEAMS_TO_WARM": [2],
            "WEB_ANALYTICS_WARMING_MAX_ACTIVE_TEAMS": 0,
        }[key]

        result = get_teams_for_warming_op(dagster.build_op_context(), MagicMock())

        self.assertEqual(result, [2])
        mock_exec.assert_not_called()
