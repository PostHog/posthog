from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.product_analytics.backend.presentation.insight_write_validation import (
    InsightWriteRejection,
    find_insight_write_rejection,
)

PAGEVIEW_SERIES = [{"kind": "EventsNode", "event": "$pageview"}]
PAGEVIEW_FILTER_EVENTS = [{"id": "$pageview", "type": "events"}]


class TestInsightWriteValidation(BaseTest):
    def _find(
        self,
        *,
        query: dict[str, Any] | None = None,
        filters: dict[str, Any] | None = None,
        unchanged_query: dict[str, Any] | None = None,
    ) -> InsightWriteRejection | None:
        return find_insight_write_rejection(
            query=query,
            filters=filters,
            unchanged_query=unchanged_query,
            team=self.team,
            user=self.user,
        )

    @parameterized.expand(
        [
            (
                "empty trends series",
                {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": []}},
                None,
                "insight_requires_at_least_one_series",
                "query",
            ),
            (
                "empty trends series, unwrapped",
                {"kind": "TrendsQuery", "series": []},
                None,
                "insight_requires_at_least_one_series",
                "query",
            ),
            (
                "empty lifecycle series",
                {"kind": "InsightVizNode", "source": {"kind": "LifecycleQuery", "series": []}},
                None,
                "insight_requires_at_least_one_series",
                "query",
            ),
            (
                "funnel with a single step",
                {"kind": "InsightVizNode", "source": {"kind": "FunnelsQuery", "series": PAGEVIEW_SERIES}},
                None,
                "funnels_require_at_least_two_steps",
                "query",
            ),
            (
                "legacy filters that convert to an empty series",
                None,
                {"insight": "TRENDS", "events": []},
                "insight_requires_at_least_one_series",
                "filters",
            ),
        ]
    )
    def test_rejects_a_query_no_runner_can_execute(
        self,
        _name: str,
        query: dict | None,
        filters: dict | None,
        expected_code: str,
        expected_source: str,
    ) -> None:
        rejection = self._find(query=query, filters=filters)

        assert rejection is not None
        assert rejection.rule_code == expected_code
        assert rejection.write_source == expected_source

    @parameterized.expand(
        [
            (
                "trends with a series",
                {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": PAGEVIEW_SERIES}},
                None,
                None,
            ),
            (
                "hogql",
                {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "select 1"}},
                None,
                None,
            ),
            ("a kind no runner owns", {"kind": "SomeQueryWeDoNotHave", "series": []}, None, None),
            ("a payload no runner can parse", {"kind": "TrendsQuery", "series": [{"nope": True}]}, None, None),
            ("legacy filters with an event", None, {"insight": "TRENDS", "events": PAGEVIEW_FILTER_EVENTS}, None),
            (
                "a query that renders, alongside filters that would not",
                {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": PAGEVIEW_SERIES}},
                {"insight": "TRENDS", "events": []},
                None,
            ),
            (
                "filters the rules refuse, on an insight whose stored query renders",
                None,
                {"insight": "TRENDS", "events": []},
                {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": PAGEVIEW_SERIES}},
            ),
            ("nothing written", None, None, None),
        ]
    )
    def test_accepts_everything_the_rules_do_not_refuse(
        self, _name: str, query: dict | None, filters: dict | None, unchanged_query: dict | None
    ) -> None:
        assert self._find(query=query, filters=filters, unchanged_query=unchanged_query) is None
