from typing import Any, Optional

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import WeekStartDay


class TestLifecycleInsightActors(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_test_events(self):
        data = [
            (
                "p1",
                [
                    "2020-01-11T12:00:00Z",
                    "2020-01-12T12:00:00Z",
                    "2020-01-13T12:00:00Z",
                    "2020-01-15T12:00:00Z",
                    "2020-01-17T12:00:00Z",
                    "2020-01-19T12:00:00Z",
                ],
            ),
            ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
            ("p3", ["2020-01-12T12:00:00Z"]),
            ("p4", ["2020-01-15T12:00:00Z"]),
        ]
        for distinct_id, timestamps in data:
            with freeze_time(timestamps[0]):
                _create_person(
                    team_id=self.team.pk,
                    distinct_ids=[distinct_id],
                    properties={
                        "name": distinct_id,
                        **({"email": "test@posthog.com"} if distinct_id == "p1" else {}),
                    },
                )
            for timestamp in timestamps:
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    properties={"$group_0": "org:1"},
                )

    def select(self, query: str, placeholders: Optional[dict[str, Any]] = None):
        return execute_hogql_query(query=query, team=self.team, placeholders=placeholders or {})

    @snapshot_clickhouse_queries
    def test_insight_persons_lifecycle_query(self):
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.save()

        date_from = "2020-01-09"
        date_to = "2020-01-19"

        response = self.select(
            """
            select * from (
                <ActorsQuery select={['properties.name as n']}>
                    <InsightActorsQuery day='2020-01-12' status='returning'>
                        <LifecycleQuery
                            dateRange={<DateRange date_from={{date_from}} date_to={{date_to}} />}
                            series={[<EventsNode event='$pageview' math='total' />]}
                        />
                    </InsightActorsQuery>
                </ActorsQuery>
            )
            """,
            {"date_from": ast.Constant(value=date_from), "date_to": ast.Constant(value=date_to)},
        )

        self.assertEqual([("p1",)], response.results)

    # A week bucket is anchored on the team's week start, so the same events put the returning
    # actors on a different day under each setting.
    def test_insight_persons_lifecycle_query_week_monday(self):
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.week_start_day = WeekStartDay.MONDAY
        self.team.save()

        date_from = "2020-01-09"
        date_to = "2020-01-19"

        response = self.select(
            """
            select * from (
                <ActorsQuery select={['properties.name as n']}>
                    <InsightActorsQuery day='2020-01-13' status='returning'>
                        <LifecycleQuery
                            interval='week'
                            dateRange={<DateRange date_from={{date_from}} date_to={{date_to}} />}
                            series={[<EventsNode event='$pageview' math='total' />]}
                        />
                    </InsightActorsQuery>
                </ActorsQuery>
            )
            """,
            {"date_from": ast.Constant(value=date_from), "date_to": ast.Constant(value=date_to)},
        )

        self.assertEqual([("p1",)], response.results)

    def test_insight_persons_lifecycle_query_week_sunday(self):
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.week_start_day = WeekStartDay.SUNDAY
        self.team.save()

        date_from = "2020-01-09"
        date_to = "2020-01-19"

        response = self.select(
            """
            select * from (
                <ActorsQuery select={['properties.name as n']}>
                    <InsightActorsQuery day='2020-01-12' status='returning'>
                        <LifecycleQuery
                            interval='week'
                            dateRange={<DateRange date_from={{date_from}} date_to={{date_to}} />}
                            series={[<EventsNode event='$pageview' math='total' />]}
                        />
                    </InsightActorsQuery>
                </ActorsQuery>
            )
            """,
            {"date_from": ast.Constant(value=date_from), "date_to": ast.Constant(value=date_to)},
        )

        self.assertEqual([("p1",), ("p2",)], response.results)
