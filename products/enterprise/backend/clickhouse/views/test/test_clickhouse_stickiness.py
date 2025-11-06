from datetime import datetime, timedelta

from freezegun.api import freeze_time
from posthog.test.base import ClickhouseTestMixin, _create_event, _create_person, snapshot_clickhouse_queries

from django.test.client import Client

from posthog.api.test.test_stickiness import get_stickiness_time_series_ok, stickiness_test_factory
from posthog.models.action import Action
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.group.util import create_group
from posthog.queries.util import get_earliest_timestamp
from posthog.test.test_journeys import journeys_for

from products.enterprise.backend.clickhouse.queries.stickiness import ClickhouseStickiness


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    event_name = kwargs.pop("event_name")
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": event_name}])
    return action


def get_people_from_url_ok(client: Client, url: str):
    response = client.get("/" + url)
    assert response.status_code == 200, response.content
    return response.json()["results"][0]["people"]


class TestClickhouseStickiness(
    ClickhouseTestMixin,
    stickiness_test_factory(
        ClickhouseStickiness,
        _create_event,
        _create_person,
        _create_action,
        get_earliest_timestamp,
    ),
):
    @snapshot_clickhouse_queries
    def test_filter_by_group_properties(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key=f"org:1",
            properties={"industry": "technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key=f"org:2",
            properties={"industry": "agriculture"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key=f"org:3",
            properties={"industry": "technology"},
        )
        create_group(team_id=self.team.pk, group_type_index=0, group_key=f"org:4", properties={})
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key=f"company:1",
            properties={"industry": "technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key=f"instance:1",
            properties={},
        )

        self._create_multiple_people(
            period=timedelta(weeks=1),
            event_properties=lambda i: {
                "$group_0": f"org:{i}",
                "$group_1": "instance:1",
            },
        )

        with freeze_time("2020-02-15T13:01:01Z"):
            data = get_stickiness_time_series_ok(
                client=self.client,
                team=self.team,
                request={
                    "shown_as": "Stickiness",
                    "date_from": "2020-01-01",
                    "date_to": "2020-02-15",
                    "events": [{"id": "watched movie"}],
                    "properties": [
                        {
                            "key": "industry",
                            "value": "technology",
                            "type": "group",
                            "group_type_index": 0,
                        }
                    ],
                    "interval": "week",
                },
            )

        assert data["watched movie"][1].value == 1
        assert data["watched movie"][2].value == 0
        assert data["watched movie"][3].value == 1

    @snapshot_clickhouse_queries
    def test_aggregate_by_groups(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key=f"org:0",
            properties={"industry": "technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key=f"org:1",
            properties={"industry": "agriculture"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key=f"org:2",
            properties={"industry": "technology"},
        )
        self._create_multiple_people(
            period=timedelta(weeks=1),
            event_properties=lambda i: {"$group_0": f"org:{i // 2}"},
        )

        with freeze_time("2020-02-15T13:01:01Z"):
            data = get_stickiness_time_series_ok(
                client=self.client,
                team=self.team,
                request={
                    "shown_as": "Stickiness",
                    "date_from": "2020-01-01",
                    "date_to": "2020-02-15",
                    "events": [
                        {
                            "id": "watched movie",
                            "math": "unique_group",
                            "math_group_type_index": 0,
                        }
                    ],
                    "interval": "week",
                },
            )

        assert data["watched movie"][1].value == 2
        assert data["watched movie"][2].value == 0
        assert data["watched movie"][3].value == 1

    @snapshot_clickhouse_queries
    def test_timezones(self):
        journeys_for(
            {
                "person1": [
                    {
                        "event": "$pageview",
                        "timestamp": datetime(2021, 5, 2, 1),
                    },  # this time will fall on 5/1 in US Pacific
                    {"event": "$pageview", "timestamp": datetime(2021, 5, 2, 9)},
                    {"event": "$pageview", "timestamp": datetime(2021, 5, 4, 3)},
                ]
            },
            self.team,
        )

        data = ClickhouseStickiness().run(
            filter=StickinessFilter(
                data={
                    "shown_as": "Stickiness",
                    "date_from": "2021-05-01",
                    "date_to": "2021-05-15",
                    "events": [{"id": "$pageview"}],
                },
                team=self.team,
            ),
            team=self.team,
        )

        self.assertEqual(data[0]["days"], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15])
        self.assertEqual(data[0]["data"], [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])

        self.team.timezone = "US/Pacific"
        self.team.save()

        data_pacific = ClickhouseStickiness().run(
            filter=StickinessFilter(
                data={
                    "shown_as": "Stickiness",
                    "date_from": "2021-05-01",
                    "date_to": "2021-05-15",
                    "events": [{"id": "$pageview"}],
                },
                team=self.team,
            ),
            team=self.team,
        )

        self.assertEqual(data_pacific[0]["days"], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15])
        self.assertEqual(data_pacific[0]["data"], [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
