from posthog.test.base import BaseTest

from parameterized import parameterized

from products.web_analytics.dags.cache_warming import maybe_opt_into_lazy_precompute


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
