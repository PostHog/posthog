from typing import Any, Optional

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import BreakdownFilter, DateRange, EventsNode, FunnelsFilter, FunnelsQuery, StepOrderValue

from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query

from products.product_analytics.backend.hogql_queries.funnels.funnels_query_runner import FunnelsQueryRunner

FLAG_PATH = "posthog.hogql.insight_table_functions.posthoganalytics.feature_enabled"


class TestFunnelTableFunction(ClickhouseTestMixin, APIBaseTest):
    def _seed(self) -> None:
        journeys: dict[str, list[tuple[str, str, str]]] = {
            "converts_fully": [
                ("signed_up", "2024-01-02T10:00:00Z", "Chrome"),
                ("onboarded", "2024-01-02T11:00:00Z", "Chrome"),
                ("purchased", "2024-01-03T10:00:00Z", "Chrome"),
            ],
            "stops_at_two": [
                ("signed_up", "2024-01-02T10:00:00Z", "Safari"),
                ("onboarded", "2024-01-04T10:00:00Z", "Safari"),
            ],
            "out_of_order": [
                ("onboarded", "2024-01-02T09:00:00Z", "Safari"),
                ("signed_up", "2024-01-02T10:00:00Z", "Safari"),
                ("purchased", "2024-01-02T12:00:00Z", "Safari"),
            ],
            "interrupted": [
                ("signed_up", "2024-01-05T10:00:00Z", "Chrome"),
                ("$pageview", "2024-01-05T10:30:00Z", "Chrome"),
                ("onboarded", "2024-01-05T11:00:00Z", "Chrome"),
            ],
            "first_step_only": [("signed_up", "2024-01-06T10:00:00Z", "Firefox")],
        }
        for distinct_id, events in journeys.items():
            _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
            for event, timestamp, browser in events:
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    properties={"$browser": browser},
                )

    def _run(self, sql: str) -> list[Any]:
        with patch(FLAG_PATH, return_value=True):
            return execute_hogql_query(query=sql, team=self.team).results

    @parameterized.expand(
        [
            (order.value, breakdown)
            for order in (StepOrderValue.ORDERED, StepOrderValue.STRICT, StepOrderValue.UNORDERED)
            for breakdown in (None, "$browser")
        ]
    )
    def test_matches_funnel_insight(self, order: str, breakdown: Optional[str]) -> None:
        self._seed()
        steps = ["signed_up", "onboarded", "purchased"]
        insight = (
            FunnelsQueryRunner(
                query=FunnelsQuery(
                    series=[EventsNode(event=step, name=step) for step in steps],
                    dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-10"),
                    funnelsFilter=FunnelsFilter(funnelOrderType=StepOrderValue(order)),
                    breakdownFilter=BreakdownFilter(breakdown=breakdown, breakdown_type="event") if breakdown else None,
                ),
                team=self.team,
            )
            .calculate()
            .results
        )
        insight_funnels = insight if breakdown else [insight]
        expected = sorted(
            (
                step["order"] + 1,
                step["name"],
                step["breakdown_value"] if breakdown else None,
                step["count"],
                step["average_conversion_time"],
                step["median_conversion_time"],
            )
            for funnel in insight_funnels
            for step in funnel
        )

        breakdown_arg = f", breakdown := '{breakdown}'" if breakdown else ""
        rows = self._run(
            f"""
            SELECT step, step_name, breakdown_value, count, average_conversion_time, median_conversion_time
            FROM funnel(
                steps := ['signed_up', 'onboarded', 'purchased'],
                date_from := '2024-01-01',
                date_to := '2024-01-10',
                order := '{order}'{breakdown_arg}
            )
            """
        )

        assert any(row[3] > 0 for row in expected)
        assert sorted(tuple(row) for row in rows) == expected

    def test_composes_like_a_table(self) -> None:
        self._seed()

        rows = self._run(
            """
            WITH f AS (
                SELECT * FROM funnel(steps := ['signed_up', 'onboarded'], date_from := '2024-01-01', date_to := '2024-01-10')
            )
            SELECT step_name, count, round(conversion_rate, 2) FROM f WHERE step > 1
            """
        )

        assert rows == [("onboarded", 3, 0.6)]

    @parameterized.expand(
        [
            ("positional", "funnel(['a', 'b'])", "only takes named arguments"),
            ("unknown", "funnel(steps := ['a', 'b'], stepz := 1)", "has no argument 'stepz'"),
            ("missing_steps", "funnel(order := 'strict')", "missing required argument 'steps'"),
            ("one_step", "funnel(steps := ['a'])", "needs at least 2 events"),
            ("steps_not_strings", "funnel(steps := [1, 2])", "must be an array of strings"),
            ("bad_order", "funnel(steps := ['a', 'b'], order := 'sideways')", "'ordered', 'strict' or 'unordered'"),
            ("bad_window", "funnel(steps := ['a', 'b'], window := 14)", "must be a positive interval"),
        ]
    )
    def test_rejects_invalid_arguments(self, _name: str, call: str, message: str) -> None:
        with self.assertRaisesRegex(QueryError, message):
            self._run(f"SELECT * FROM {call}")

    def test_unavailable_when_flag_is_off(self) -> None:
        with patch(FLAG_PATH, return_value=False), self.assertRaisesRegex(QueryError, "Unknown table function"):
            execute_hogql_query(query="SELECT * FROM funnel(steps := ['a', 'b'])", team=self.team)
