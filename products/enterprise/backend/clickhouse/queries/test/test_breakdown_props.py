import pytest
from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    snapshot_clickhouse_queries,
)

from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.group.util import create_group
from posthog.queries.breakdown_props import _to_bucketing_expression, get_breakdown_prop_values
from posthog.queries.trends.util import process_math
from posthog.test.test_utils import create_group_type_mapping_without_created_at


class TestBreakdownProps(ClickhouseTestMixin, APIBaseTest):
    @also_test_with_materialized_columns(
        event_properties=["$host", "distinct_id"],
        person_properties=["$browser", "email"],
    )
    @snapshot_clickhouse_queries
    def test_breakdown_person_props(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"$browser": "test"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        self.team.test_account_filters = [
            {
                "key": "email",
                "type": "person",
                "value": "posthog.com",
                "operator": "not_icontains",
            },
            {
                "key": "$host",
                "type": "event",
                "value": [
                    "127.0.0.1:3000",
                    "127.0.0.1:5000",
                    "localhost:5000",
                    "localhost:8000",
                ],
                "operator": "is_not",
            },
            {
                "key": "distinct_id",
                "type": "event",
                "value": "posthog.com",
                "operator": "not_icontains",
            },
        ]
        self.team.save()
        with freeze_time("2020-01-04T13:01:01Z"):
            filter = Filter(
                data={
                    "insight": "FUNNELS",
                    "properties": [],
                    "filter_test_accounts": True,
                    "events": [
                        {
                            "id": "$pageview",
                            "name": "$pageview",
                            "type": "events",
                            "order": 0,
                        }
                    ],
                    "actions": [],
                    "funnel_viz_type": "steps",
                    "display": "FunnelViz",
                    "interval": "day",
                    "breakdown": "$browser",
                    "breakdown_type": "person",
                    "breakdown_limit": 5,
                    "date_from": "-14d",
                    "funnel_window_days": 14,
                }
            )
            res = get_breakdown_prop_values(
                filter,
                Entity({"id": "$pageview", "type": "events"}),
                "count(*)",
                self.team,
            )
            self.assertEqual(res[0], ["test"])

    def test_breakdown_person_props_with_entity_filter(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"$browser": "test"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )
        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"$browser": "test2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        cohort = Cohort.objects.create(
            team=self.team,
            name="a",
            groups=[{"properties": [{"key": "$browser", "value": "test", "type": "person"}]}],
        )
        cohort.calculate_people_ch(pending_version=0)

        entity_params = [
            {
                "id": "$pageview",
                "name": "$pageview",
                "type": "events",
                "order": 0,
                "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
            }
        ]
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            with freeze_time("2020-01-04T13:01:01Z"):
                filter = Filter(
                    data={
                        "insight": "FUNNELS",
                        "properties": [],
                        "filter_test_accounts": False,
                        "events": entity_params,
                        "actions": [],
                        "funnel_viz_type": "steps",
                        "display": "FunnelViz",
                        "interval": "day",
                        "breakdown": "$browser",
                        "breakdown_type": "person",
                        "breakdown_limit": 5,
                        "date_from": "-14d",
                        "funnel_window_days": 14,
                    }
                )
                res = get_breakdown_prop_values(filter, Entity(entity_params[0]), "count(*)", self.team)
                self.assertEqual(res[0], ["test"])

    @snapshot_clickhouse_queries
    def test_breakdown_person_props_with_entity_filter_and_or_props_with_partial_pushdown(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p1"],
            properties={"$browser": "test", "$os": "test"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p2"],
            properties={"$browser": "test2", "$os": "test2"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val2"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p3"],
            properties={"$browser": "test3", "$os": "test3"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val3"},
        )

        entity_params = [
            {
                "id": "$pageview",
                "name": "$pageview",
                "type": "events",
                "order": 0,
                "properties": [
                    {
                        "key": "$browser",
                        "type": "person",
                        "value": "test",
                        "operator": "icontains",
                    }
                ],
            }
        ]
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            with freeze_time("2020-01-04T13:01:01Z"):
                filter = Filter(
                    data={
                        "insight": "FUNNELS",
                        "properties": {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$os",
                                    "type": "person",
                                    "value": "test2",
                                    "operator": "exact",
                                },
                                {
                                    "key": "key",
                                    "type": "event",
                                    "value": "val",
                                    "operator": "exact",
                                },
                            ],
                        },
                        "filter_test_accounts": False,
                        "events": entity_params,
                        "actions": [],
                        "funnel_viz_type": "steps",
                        "display": "FunnelViz",
                        "interval": "day",
                        "breakdown": "$browser",
                        "breakdown_type": "person",
                        "breakdown_limit": 5,
                        "date_from": "-14d",
                        "funnel_window_days": 14,
                    }
                )
                res = sorted(get_breakdown_prop_values(filter, Entity(entity_params[0]), "count(*)", self.team)[0])
                self.assertEqual(res, ["test", "test2"])

    @snapshot_clickhouse_queries
    def test_breakdown_group_props(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="company", group_type_index=1
        )

        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"industry": "technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:7",
            properties={"industry": "finance"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:8",
            properties={"industry": "another", "out": 1},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:10",
            properties={"industry": "foobar"},
        )
        # :TRICKY: Test group type overlapping
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="org:8",
            properties={"industry": "foobar"},
        )

        for org_index in range(5, 9):
            _create_event(
                event="$pageview",
                distinct_id="person1",
                team=self.team,
                properties={"$group_0": f"org:{org_index}"},
                timestamp="2020-01-02T12:00:00Z",
            )

        filter = Filter(
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "breakdown": "industry",
                "breakdown_type": "group",
                "breakdown_group_type_index": 0,
                "breakdown_limit": 5,
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
                "properties": [
                    {
                        "key": "out",
                        "value": "",
                        "type": "group",
                        "group_type_index": 0,
                        "operator": "is_not_set",
                    }
                ],
            },
            team=self.team,
        )
        result = get_breakdown_prop_values(filter, filter.entities[0], "count(*)", self.team)
        self.assertEqual(result[0], ["finance", "technology"])

        filter = Filter(
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "breakdown": "industry",
                "breakdown_type": "group",
                "breakdown_group_type_index": 0,
                "breakdown_limit": 5,
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "out",
                            "value": "",
                            "type": "group",
                            "group_type_index": 0,
                            "operator": "is_not_set",
                        }
                    ],
                },
            }
        )
        result = get_breakdown_prop_values(filter, filter.entities[0], "count(*)", self.team)
        self.assertEqual(result[0], ["finance", "technology"])

    @snapshot_clickhouse_queries
    def test_breakdown_session_props(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p1"],
            properties={"$browser": "test", "$os": "test"},
        )

        # 20 second session that starts before the time range
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-01T23:59:50Z",
            properties={"$session_id": "1"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T00:00:10Z",
            properties={"$session_id": "1"},
        )

        # 70 second session
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
            properties={"$session_id": "2"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:01:10Z",
            properties={"$session_id": "2"},
        )

        filter = Filter(
            data={
                "date_from": "2020-01-02T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "breakdown": "$session_duration",
                "breakdown_type": "session",
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
            }
        )
        result = get_breakdown_prop_values(filter, filter.entities[0], "count(*)", self.team)
        self.assertEqual(result[0], [70, 20])

    @snapshot_clickhouse_queries
    def test_breakdown_with_math_property_session(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p1"],
            properties={"$browser": "test", "$os": "test"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p2"],
            properties={"$browser": "mac", "$os": "test"},
        )

        # 20 second session that starts before the time range
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-01T23:59:50Z",
            properties={"$session_id": "1"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T00:00:10Z",
            properties={"$session_id": "1"},
        )

        # 70 second session
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
            properties={"$session_id": "2"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:01:10Z",
            properties={"$session_id": "2"},
        )

        # 10 second session for second person with different browser, but more absolute
        # events than first person
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:00Z",
            properties={"$session_id": "3"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:01Z",
            properties={"$session_id": "3"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:02Z",
            properties={"$session_id": "3"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:03Z",
            properties={"$session_id": "3"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:04Z",
            properties={"$session_id": "3"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:10Z",
            properties={"$session_id": "3"},
        )

        filter = Filter(
            data={
                "date_from": "2020-01-02T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "breakdown": "$browser",
                "breakdown_type": "person",
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "math": "sum",
                        "math_property": "$session_duration",
                    }
                ],
            }
        )
        aggregate_operation, _, _ = process_math(filter.entities[0], self.team, filter=filter)

        result = get_breakdown_prop_values(filter, filter.entities[0], aggregate_operation, self.team)
        # test should come first, based on aggregate operation, even if absolute count of events for
        # mac is higher
        self.assertEqual(result[0], ["test", "mac"])

        result = get_breakdown_prop_values(filter, filter.entities[0], "count(*)", self.team)
        self.assertEqual(result[0], ["mac", "test"])


@pytest.mark.parametrize(
    "test_input,expected",
    [
        (0, "arrayCompact(arrayMap(x -> floor(x, 2), quantiles(0,1)(value)))"),
        (1, "arrayCompact(arrayMap(x -> floor(x, 2), quantiles(0,1)(value)))"),
        (
            2,
            "arrayCompact(arrayMap(x -> floor(x, 2), quantiles(0.00,0.50,1.00)(value)))",
        ),
        (
            3,
            "arrayCompact(arrayMap(x -> floor(x, 2), quantiles(0.00,0.33,0.67,1.00)(value)))",
        ),
        (
            5,
            "arrayCompact(arrayMap(x -> floor(x, 2), quantiles(0.00,0.20,0.40,0.60,0.80,1.00)(value)))",
        ),
        (
            7,
            "arrayCompact(arrayMap(x -> floor(x, 2), quantiles(0.00,0.14,0.29,0.43,0.57,0.71,0.86,1.00)(value)))",
        ),
        (
            10,
            "arrayCompact(arrayMap(x -> floor(x, 2), quantiles(0.00,0.10,0.20,0.30,0.40,0.50,0.60,0.70,0.80,0.90,1.00)(value)))",
        ),
    ],
)
def test_bucketing_expression(test_input, expected):
    result = _to_bucketing_expression(test_input)

    assert result == expected
