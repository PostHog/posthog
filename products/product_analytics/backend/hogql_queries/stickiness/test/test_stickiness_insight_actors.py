from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

from posthog.hogql.query import execute_hogql_query

from posthog.models.group.util import create_group
from posthog.test.test_utils import create_group_type_mapping_without_created_at


class TestStickinessInsightActors(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_test_groups(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:1",
            properties={"name": "org1"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:2",
            properties={"name": "org2"},
        )

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

    def select(self, query: str):
        return execute_hogql_query(query=query, team=self.team)

    @snapshot_clickhouse_queries
    def test_insight_persons_stickiness_query(self):
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.save()

        response = self.select(
            """
            select * from (
                <ActorsQuery select={['properties.name']}>
                    <InsightActorsQuery day={2}>
                        <StickinessQuery
                            dateRange={<DateRange date_from='2020-01-09' date_to='2020-01-19' />}
                            series={[<EventsNode event='$pageview' />]}
                        />
                    </InsightActorsQuery>
                </ActorsQuery>
            )
            """
        )

        self.assertEqual([("p2",)], response.results)

    @snapshot_clickhouse_queries
    def test_insight_persons_stickiness_groups_query(self):
        self._create_test_groups()
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.save()

        response = self.select(
            """
            select * from (
                <ActorsQuery select={['properties.name']}>
                    <InsightActorsQuery day={7}>
                        <StickinessQuery
                            dateRange={<DateRange date_from='2020-01-01' date_to='2020-01-19' />}
                            series={[<EventsNode event='$pageview' math='unique_group' math_group_type_index={0} />]}
                        />
                    </InsightActorsQuery>
                </ActorsQuery>
            )
            """
        )

        self.assertEqual([("org1",)], response.results)
