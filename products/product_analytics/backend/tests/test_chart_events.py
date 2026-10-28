import json
from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.query import execute_hogql_query

from products.actions.backend.models.action import Action
from products.product_analytics.backend.chart_events import ChartEvents, chart_events

SERIES = {"kind": "EventsNode", "event": "signed up"}
STEPS = [SERIES, {"kind": "EventsNode", "event": "paid"}]
PAID_PRO = {
    "kind": "EventsNode",
    "event": "paid",
    "properties": [{"key": "plan", "value": "pro", "operator": "exact", "type": "event"}],
}
COMBINED = {"kind": "GroupNode", "operator": "OR", "nodes": [SERIES, PAID_PRO]}
ACTION = {"kind": "ActionsNode", "id": "ACTION_ID"}
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
        for days_ago, plan in ((2, "pro"), (4, "free")):
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="person",
                timestamp=NOW - timedelta(days=days_ago),
                properties={"plan": plan},
            )
        _create_event(team=self.team, event="other", distinct_id="person", timestamp=NOW - timedelta(days=1))
        flush_persons_and_events()
        self.action = Action.objects.create(
            team=self.team,
            name="Signed up or paid for pro",
            steps_json=[{"event": "paid", "properties": PAID_PRO["properties"]}, {"event": "signed up"}],
        )

    def _chart_events(self, query: dict[str, Any]) -> ChartEvents:
        query = json.loads(json.dumps(query).replace('"ACTION_ID"', str(self.action.pk)))
        events = chart_events({**query, "dateRange": LAST_WEEK}, self.team, self.user)
        assert events is not None
        return events

    def _count(self, events: ChartEvents, where: ast.Expr) -> int:
        response = execute_hogql_query(
            events.select("SELECT count() FROM events", where=where),
            team=self.team,
            modifiers=events.modifiers,
            context=HogQLContext(team_id=self.team.pk, database=events.database),
        )
        return response.results[0][0]

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
            ("funnel_combined_step", {"kind": "FunnelsQuery", "series": [COMBINED, SERIES]}, 3),
            ("stickiness_action_series", {"kind": "StickinessQuery", "series": [ACTION]}, 3),
            (
                "funnel_action_in_a_combined_step",
                {
                    "kind": "FunnelsQuery",
                    "series": [{"kind": "GroupNode", "operator": "OR", "nodes": [SERIES, ACTION]}, SERIES],
                },
                3,
            ),
        ]
    )
    def test_reads_the_events_of_every_period_the_chart_reads(
        self, _name: str, query: dict[str, Any], expected: int
    ) -> None:
        events = self._chart_events(query)

        assert self._count(events, events.where) == expected

    @parameterized.expand([("combined_series", COMBINED, 4), ("action_series", ACTION, 4)])
    def test_sizes_a_series_by_its_event_names(self, _name: str, series: dict[str, Any], expected: int) -> None:
        events = self._chart_events({"kind": "FunnelsQuery", "series": [series, SERIES]})

        assert self._count(events, events.sort_key_where) == expected
