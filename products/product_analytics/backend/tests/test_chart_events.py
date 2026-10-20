from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.query import execute_hogql_query

from products.product_analytics.backend.chart_events import chart_events

SERIES = {"kind": "EventsNode", "event": "signed up"}
STEPS = [SERIES, {"kind": "EventsNode", "event": "paid"}]
NOW = datetime(2026, 3, 10, 12, tzinfo=UTC)
LAST_WEEK = {"date_from": "-7d"}


class TestChartEvents(BaseTest):
    @parameterized.expand(
        [
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
            ("stickiness_compare", {"kind": "StickinessQuery", "series": [SERIES], "compareFilter": {"compare": True}}),
        ]
    )
    def test_finds_the_events_the_chart_reads(self, _name: str, source: dict[str, Any]) -> None:
        assert chart_events(source, self.team, self.user) is not None


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
            ("stickiness", {"kind": "StickinessQuery", "series": [SERIES]}, 2),
            (
                "funnel_compared_to_the_previous_period",
                {"kind": "FunnelsQuery", "series": [SERIES, SERIES], "compareFilter": {"compare": True}},
                3,
            ),
            (
                "filter_with_a_lambda_argument_named_like_a_select_alias",
                {
                    "kind": "FunnelsQuery",
                    "series": [SERIES, SERIES],
                    "properties": [{"type": "hogql", "key": "arrayExists(step_0 -> step_0 > 10, [1, 20])"}],
                },
                2,
            ),
        ]
    )
    def test_reads_the_events_of_every_period_the_chart_reads(
        self, _name: str, query: dict[str, Any], expected: int
    ) -> None:
        events = chart_events({**query, "dateRange": LAST_WEEK}, self.team, self.user)
        assert events is not None

        response = execute_hogql_query(
            events.select("SELECT count() FROM events", where=events.where),
            team=self.team,
            modifiers=events.modifiers,
            context=HogQLContext(team_id=self.team.pk, database=events.database),
        )

        assert response.results[0][0] == expected
