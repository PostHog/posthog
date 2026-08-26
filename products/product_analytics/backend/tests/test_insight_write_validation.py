from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.product_analytics.backend.insight_write_validation import find_insight_write_rejection

TRENDS_SERIES = [{"kind": "EventsNode", "event": "$pageview"}]


class TestInsightWriteValidation(BaseTest):
    def _find(self, *, query: dict[str, Any] | None = None, filters: dict[str, Any] | None = None) -> Any:
        return find_insight_write_rejection(query=query, filters=filters, team=self.team, user=self.user)

    @parameterized.expand(
        [
            (
                "empty trends series",
                {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": []}},
                "insight_requires_at_least_one_series",
            ),
            (
                "empty trends series, unwrapped",
                {"kind": "TrendsQuery", "series": []},
                "insight_requires_at_least_one_series",
            ),
            (
                "empty lifecycle series",
                {"kind": "InsightVizNode", "source": {"kind": "LifecycleQuery", "series": []}},
                "insight_requires_at_least_one_series",
            ),
            (
                "funnel with a single step",
                {"kind": "InsightVizNode", "source": {"kind": "FunnelsQuery", "series": TRENDS_SERIES}},
                "funnels_require_at_least_two_steps",
            ),
        ]
    )
    def test_rejects_a_query_no_runner_can_execute(self, _name: str, query: dict, expected_code: str) -> None:
        rejection = self._find(query=query)

        assert rejection is not None
        assert rejection.rule_code == expected_code
        assert rejection.write_source == "query"

    @parameterized.expand(
        [
            (
                "trends with a series",
                {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": TRENDS_SERIES}},
            ),
            ("hogql", {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "select 1"}}),
            ("a kind no runner owns", {"kind": "SomeQueryWeDoNotHave", "series": []}),
            ("a payload no runner can parse", {"kind": "TrendsQuery", "series": [{"nope": True}]}),
            ("nothing written", None),
        ]
    )
    def test_accepts_everything_the_rules_do_not_refuse(self, _name: str, query: dict | None) -> None:
        assert self._find(query=query) is None

    def test_rejects_legacy_filters_that_convert_to_an_empty_series(self) -> None:
        rejection = self._find(filters={"insight": "TRENDS", "events": []})

        assert rejection is not None
        assert rejection.rule_code == "insight_requires_at_least_one_series"
        assert rejection.write_source == "filters"

    def test_accepts_legacy_filters_with_an_event(self) -> None:
        assert self._find(filters={"insight": "TRENDS", "events": [{"id": "$pageview", "type": "events"}]}) is None
