from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query

from products.product_analytics.backend.chart_events import chart_events

SERIES = {"kind": "EventsNode", "event": "signed up"}
STEPS = [SERIES, {"kind": "EventsNode", "event": "paid"}]
NOW = datetime(2026, 3, 10, 12, tzinfo=UTC)
LAST_WEEK = {"date_from": "-7d"}
TREND_FLAGS = "products.product_analytics.backend.hogql_queries.trends.trends_query_builder.feature_enabled_or_false"


class TestChartEvents(BaseTest):
    @parameterized.expand(
        [
            ("weekly_active", {"kind": "TrendsQuery", "series": [{**SERIES, "math": "weekly_active"}]}),
            (
                "sum_of_a_session_property",
                {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            **SERIES,
                            "math": "avg",
                            "math_property": "$session_duration",
                            "math_property_type": "session_properties",
                        }
                    ],
                },
            ),
            ("compare", {"kind": "TrendsQuery", "series": [SERIES], "compareFilter": {"compare": True}}),
            ("formula", {"kind": "TrendsQuery", "series": [SERIES, SERIES], "trendsFilter": {"formula": "A / B"}}),
            ("total_value", {"kind": "TrendsQuery", "series": [SERIES], "trendsFilter": {"display": "ActionsPie"}}),
            (
                "property_breakdown",
                {"kind": "TrendsQuery", "series": [SERIES], "breakdownFilter": {"breakdown": "$browser"}},
            ),
            (
                "histogram_breakdown",
                {
                    "kind": "TrendsQuery",
                    "series": [SERIES],
                    "breakdownFilter": {"breakdown": "price", "breakdown_histogram_bin_count": 5},
                },
            ),
            (
                "funnel_exclusion",
                {
                    "kind": "FunnelsQuery",
                    "series": STEPS,
                    "funnelsFilter": {
                        "exclusions": [{"kind": "EventsNode", "event": "left", "funnelFromStep": 0, "funnelToStep": 1}]
                    },
                },
            ),
            ("funnel_trends", {"kind": "FunnelsQuery", "series": STEPS, "funnelsFilter": {"funnelVizType": "trends"}}),
            (
                "funnel_time_to_convert",
                {"kind": "FunnelsQuery", "series": STEPS, "funnelsFilter": {"funnelVizType": "time_to_convert"}},
            ),
            (
                "stickiness_criteria",
                {
                    "kind": "StickinessQuery",
                    "series": [SERIES],
                    "stickinessFilter": {"stickinessCriteria": {"operator": "gte", "value": 3}},
                },
            ),
        ]
    )
    def test_finds_the_events_the_chart_reads(self, _name: str, source: dict[str, Any]) -> None:
        assert chart_events(source, self.team, self.user) is not None

    @parameterized.expand([("SlopeGraph",), ("BoxPlot",), ("CalendarHeatmap",)])
    def test_does_not_read_a_chart_that_runs_a_query_of_its_own(self, display: str) -> None:
        query = {
            "kind": "TrendsQuery",
            "series": [{**SERIES, "math_property": "price"}],
            "trendsFilter": {"display": display},
        }

        assert chart_events(query, self.team, self.user) is None


@time_machine.travel(NOW, tick=False)
class TestChartEventsCounts(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Two events in the last week, and one in the week before it.
        for days_ago in (3, 7, 10):
            _create_event(
                team=self.team, event="signed up", distinct_id="person", timestamp=NOW - timedelta(days=days_ago)
            )
        flush_persons_and_events()

    @parameterized.expand(
        [
            ("trends", {"kind": "TrendsQuery", "series": [SERIES]}, (), 2),
            (
                "first_time_series_compared_to_the_previous_period",
                {
                    "kind": "TrendsQuery",
                    "series": [{**SERIES, "math": "first_time_for_user"}],
                    "compareFilter": {"compare": True},
                },
                (),
                3,
            ),
            (
                "funnel_compared_to_the_previous_period",
                {"kind": "FunnelsQuery", "series": [SERIES, SERIES], "compareFilter": {"compare": True}},
                (),
                3,
            ),
            (
                "breakdown_that_reads_its_events_in_a_cte",
                {"kind": "TrendsQuery", "series": [SERIES], "breakdownFilter": {"breakdown": "$browser"}},
                ("trends-breakdown-fewer-array-ops",),
                2,
            ),
        ]
    )
    def test_reads_the_events_of_every_period_the_chart_reads(
        self, _name: str, query: dict[str, Any], flags: tuple[str, ...], expected: int
    ) -> None:
        with patch(TREND_FLAGS, side_effect=lambda flag, *args, **kwargs: flag in flags):
            events = chart_events({**query, "dateRange": LAST_WEEK}, self.team, self.user)
        assert events is not None

        response = execute_hogql_query(
            events.select("SELECT count() FROM events", where=events.where), team=self.team, modifiers=events.modifiers
        )

        assert response.results[0][0] == expected
