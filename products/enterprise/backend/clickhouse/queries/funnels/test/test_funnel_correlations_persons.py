import urllib.parse
from datetime import datetime, timedelta
from uuid import UUID

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from django.utils import timezone

from posthog.constants import INSIGHT_FUNNELS
from posthog.models import Cohort, Filter
from posthog.models.person import Person
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.tasks.calculate_cohort import insert_cohort_from_insight_filter
from posthog.test.test_journeys import journeys_for

from products.enterprise.backend.clickhouse.queries.funnels.funnel_correlation_persons import FunnelCorrelationActors

FORMAT_TIME = "%Y-%m-%d 00:00:00"
MAX_STEP_COLUMN = 0
COUNT_COLUMN = 1
PERSON_ID_COLUMN = 2


class TestClickhouseFunnelCorrelationsActors(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _setup_basic_test(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "funnel_correlation_type": "events",
        }

        filter = Filter(data=filters)

        success_target_persons = []
        failure_target_persons = []
        events_by_person = {}
        for i in range(10):
            person_id = f"user_{i}"
            person = _create_person(distinct_ids=[person_id], team_id=self.team.pk)
            events_by_person[person_id] = [{"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14)}]

            if i % 2 == 0:
                events_by_person[person_id].append(
                    {
                        "event": "positively_related",
                        "timestamp": datetime(2020, 1, 3, 14),
                    }
                )

                success_target_persons.append(str(person.uuid))

            events_by_person[person_id].append({"event": "paid", "timestamp": datetime(2020, 1, 4, 14)})

        for i in range(10, 20):
            person_id = f"user_{i}"
            person = _create_person(distinct_ids=[person_id], team_id=self.team.pk)
            events_by_person[person_id] = [{"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14)}]
            if i % 2 == 0:
                events_by_person[person_id].append(
                    {
                        "event": "negatively_related",
                        "timestamp": datetime(2020, 1, 3, 14),
                    }
                )
                failure_target_persons.append(str(person.uuid))

        # One positively_related as failure
        person_fail_id = f"user_fail"
        person_fail = _create_person(distinct_ids=[person_fail_id], team_id=self.team.pk)
        events_by_person[person_fail_id] = [
            {"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14)},
            {"event": "positively_related", "timestamp": datetime(2020, 1, 3, 14)},
        ]

        # One negatively_related as success
        person_success_id = f"user_succ"
        person_succ = _create_person(distinct_ids=[person_success_id], team_id=self.team.pk)
        events_by_person[person_success_id] = [
            {"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14)},
            {"event": "negatively_related", "timestamp": datetime(2020, 1, 3, 14)},
            {"event": "paid", "timestamp": datetime(2020, 1, 4, 14)},
        ]
        journeys_for(events_by_person, self.team, create_people=False)

        return (
            filter,
            success_target_persons,
            failure_target_persons,
            person_fail,
            person_succ,
        )

    def test_basic_funnel_correlation_with_events(self):
        (
            filter,
            success_target_persons,
            failure_target_persons,
            person_fail,
            person_succ,
        ) = self._setup_basic_test()

        # test positively_related successes
        filter = filter.shallow_clone(
            {
                "funnel_correlation_person_entity": {
                    "id": "positively_related",
                    "type": "events",
                },
                "funnel_correlation_person_converted": "TrUe",
            }
        )
        _, serialized_actors, _ = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertCountEqual([str(val["id"]) for val in serialized_actors], success_target_persons)

        # test negatively_related failures
        filter = filter.shallow_clone(
            {
                "funnel_correlation_person_entity": {
                    "id": "negatively_related",
                    "type": "events",
                },
                "funnel_correlation_person_converted": "falsE",
            }
        )

        _, serialized_actors, _ = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertCountEqual([str(val["id"]) for val in serialized_actors], failure_target_persons)

        # test positively_related failures
        filter = filter.shallow_clone(
            {
                "funnel_correlation_person_entity": {
                    "id": "positively_related",
                    "type": "events",
                },
                "funnel_correlation_person_converted": "False",
            }
        )
        _, serialized_actors, _ = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertCountEqual([str(val["id"]) for val in serialized_actors], [str(person_fail.uuid)])

        # test negatively_related successes
        filter = filter.shallow_clone(
            {
                "funnel_correlation_person_entity": {
                    "id": "negatively_related",
                    "type": "events",
                },
                "funnel_correlation_person_converted": "trUE",
            }
        )
        _, serialized_actors, _ = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertCountEqual([str(val["id"]) for val in serialized_actors], [str(person_succ.uuid)])

        # test all positively_related
        filter = filter.shallow_clone(
            {
                "funnel_correlation_person_entity": {
                    "id": "positively_related",
                    "type": "events",
                },
                "funnel_correlation_person_converted": None,
            }
        )
        _, serialized_actors, _ = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertCountEqual(
            [str(val["id"]) for val in serialized_actors],
            [*success_target_persons, str(person_fail.uuid)],
        )

        # test all negatively_related
        filter = filter.shallow_clone(
            {
                "funnel_correlation_person_entity": {
                    "id": "negatively_related",
                    "type": "events",
                },
                "funnel_correlation_person_converted": None,
            }
        )
        _, serialized_actors, _ = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertCountEqual(
            [str(val["id"]) for val in serialized_actors],
            [*failure_target_persons, str(person_succ.uuid)],
        )

    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_insight_filter.delay")
    def test_create_funnel_correlation_cohort(self, _insert_cohort_from_insight_filter):
        (
            filter,
            success_target_persons,
            failure_target_persons,
            person_fail,
            person_succ,
        ) = self._setup_basic_test()

        params = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "funnel_correlation_type": "events",
            "funnel_correlation_person_entity": {
                "id": "positively_related",
                "type": "events",
            },
            "funnel_correlation_person_converted": "TrUe",
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/?{urllib.parse.urlencode(params)}",
            {"name": "test", "is_static": True},
        ).json()

        cohort_id = response["id"]

        _insert_cohort_from_insight_filter.assert_called_once_with(
            cohort_id,
            {
                "events": "[{'id': 'user signed up', 'type': 'events', 'order': 0}, {'id': 'paid', 'type': 'events', 'order': 1}]",
                "insight": "FUNNELS",
                "date_from": "2020-01-01",
                "date_to": "2020-01-14",
                "funnel_correlation_type": "events",
                "funnel_correlation_person_entity": "{'id': 'positively_related', 'type': 'events'}",
                "funnel_correlation_person_converted": "TrUe",
            },
            self.team.pk,
        )

        insert_cohort_from_insight_filter(cohort_id, params)

        cohort = Cohort.objects.get(pk=cohort_id)
        people = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(cohort.errors_calculating, 0)
        self.assertEqual(people.count(), 5)
        self.assertEqual(cohort.count, 5)

    def test_people_arent_returned_multiple_times(self):
        people = journeys_for(
            {
                "user_1": [
                    {"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14)},
                    {
                        "event": "positively_related",
                        "timestamp": datetime(2020, 1, 3, 14),
                    },
                    # duplicate event
                    {
                        "event": "positively_related",
                        "timestamp": datetime(2020, 1, 3, 14),
                    },
                    {"event": "paid", "timestamp": datetime(2020, 1, 4, 14)},
                ]
            },
            self.team,
        )

        filter = Filter(
            data={
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-14",
                "funnel_correlation_type": "events",
                "funnel_correlation_person_entity": {
                    "id": "positively_related",
                    "type": "events",
                },
                "funnel_correlation_person_converted": "TrUe",
            }
        )
        _, serialized_actors, _ = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertCountEqual([str(val["id"]) for val in serialized_actors], [str(people["user_1"].uuid)])

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-02 00:00:00.000Z")
    def test_funnel_correlation_on_event_with_recordings(self):
        p1 = _create_person(distinct_ids=["user_1"], team=self.team, properties={"foo": "bar"})
        _create_event(
            event="$pageview",
            distinct_id="user_1",
            team=self.team,
            timestamp=timezone.now(),
            properties={"$session_id": "s2", "$window_id": "w1"},
            event_uuid="11111111-1111-1111-1111-111111111111",
        )
        _create_event(
            event="insight loaded",
            distinct_id="user_1",
            team=self.team,
            timestamp=(timezone.now() + timedelta(minutes=2)),
            properties={"$session_id": "s2", "$window_id": "w2"},
            event_uuid="31111111-1111-1111-1111-111111111111",
        )
        _create_event(
            event="insight analyzed",
            distinct_id="user_1",
            team=self.team,
            timestamp=(timezone.now() + timedelta(minutes=3)),
            properties={"$session_id": "s2", "$window_id": "w2"},
            event_uuid="21111111-1111-1111-1111-111111111111",
        )

        timestamp = datetime(2021, 1, 2, 0, 0, 0)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s2",
            distinct_id="user_1",
            first_timestamp=timestamp,
            last_timestamp=timestamp,
        )

        # Success filter
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "date_from": "2021-01-01",
                "date_to": "2021-01-08",
                "funnel_correlation_type": "events",
                "events": [
                    {"id": "$pageview", "order": 0},
                    {"id": "insight analyzed", "order": 1},
                ],
                "include_recordings": "true",
                "funnel_correlation_person_entity": {
                    "id": "insight loaded",
                    "type": "events",
                },
                "funnel_correlation_person_converted": "True",
            }
        )
        _, results, _ = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertEqual(results[0]["id"], p1.uuid)
        self.assertEqual(
            results[0]["matched_recordings"],
            [
                {
                    "events": [
                        {
                            "timestamp": timezone.now() + timedelta(minutes=3),
                            "uuid": UUID("21111111-1111-1111-1111-111111111111"),
                            "window_id": "w2",
                        }
                    ],
                    "session_id": "s2",
                }
            ],
        )

        # Drop off filter
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "date_from": "2021-01-01",
                "date_to": "2021-01-08",
                "funnel_correlation_type": "events",
                "events": [
                    {"id": "$pageview", "order": 0},
                    {"id": "insight analyzed", "order": 1},
                    {"id": "insight updated", "order": 2},
                ],
                "include_recordings": "true",
                "funnel_correlation_person_entity": {
                    "id": "insight loaded",
                    "type": "events",
                },
                "funnel_correlation_person_converted": "False",
            }
        )
        _, results, _ = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertEqual(results[0]["id"], p1.uuid)
        self.assertEqual(
            results[0]["matched_recordings"],
            [
                {
                    "events": [
                        {
                            "timestamp": timezone.now() + timedelta(minutes=3),
                            "uuid": UUID("21111111-1111-1111-1111-111111111111"),
                            "window_id": "w2",
                        }
                    ],
                    "session_id": "s2",
                }
            ],
        )

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-02 00:00:00.000Z")
    def test_funnel_correlation_on_properties_with_recordings(self):
        p1 = _create_person(distinct_ids=["user_1"], team=self.team, properties={"foo": "bar"})
        _create_event(
            event="$pageview",
            distinct_id="user_1",
            team=self.team,
            timestamp=timezone.now(),
            properties={"$session_id": "s2", "$window_id": "w1"},
            event_uuid="11111111-1111-1111-1111-111111111111",
        )
        _create_event(
            event="insight analyzed",
            distinct_id="user_1",
            team=self.team,
            timestamp=(timezone.now() + timedelta(minutes=3)),
            properties={"$session_id": "s2", "$window_id": "w2"},
            event_uuid="21111111-1111-1111-1111-111111111111",
        )

        timestamp = datetime(2021, 1, 2, 0, 0, 0)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s2",
            distinct_id="user_1",
            first_timestamp=timestamp,
            last_timestamp=timestamp,
        )

        # Success filter
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "date_from": "2021-01-01",
                "date_to": "2021-01-08",
                "funnel_correlation_type": "properties",
                "events": [
                    {"id": "$pageview", "order": 0},
                    {"id": "insight analyzed", "order": 1},
                ],
                "include_recordings": "true",
                "funnel_correlation_property_values": [
                    {
                        "key": "foo",
                        "value": "bar",
                        "operator": "exact",
                        "type": "person",
                    }
                ],
                "funnel_correlation_person_converted": "True",
            }
        )
        _, results, _ = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertEqual(results[0]["id"], p1.uuid)
        self.assertEqual(
            results[0]["matched_recordings"],
            [
                {
                    "events": [
                        {
                            "timestamp": timezone.now() + timedelta(minutes=3),
                            "uuid": UUID("21111111-1111-1111-1111-111111111111"),
                            "window_id": "w2",
                        }
                    ],
                    "session_id": "s2",
                }
            ],
        )

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-02 00:00:00.000Z")
    def test_strict_funnel_correlation_with_recordings(self):
        # First use that successfully completes the strict funnel
        p1 = _create_person(distinct_ids=["user_1"], team=self.team, properties={"foo": "bar"})
        _create_event(
            event="$pageview",
            distinct_id="user_1",
            team=self.team,
            timestamp=timezone.now(),
            properties={"$session_id": "s2", "$window_id": "w1"},
            event_uuid="11111111-1111-1111-1111-111111111111",
        )
        _create_event(
            event="insight analyzed",
            distinct_id="user_1",
            team=self.team,
            timestamp=(timezone.now() + timedelta(minutes=3)),
            properties={"$session_id": "s2", "$window_id": "w2"},
            event_uuid="31111111-1111-1111-1111-111111111111",
        )
        _create_event(
            event="insight analyzed",  # Second event should not be returned
            distinct_id="user_1",
            team=self.team,
            timestamp=(timezone.now() + timedelta(minutes=4)),
            properties={"$session_id": "s2", "$window_id": "w2"},
            event_uuid="41111111-1111-1111-1111-111111111111",
        )
        timestamp = datetime(2021, 1, 2, 0, 0, 0)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s2",
            distinct_id="user_1",
            first_timestamp=timestamp,
            last_timestamp=timestamp,
        )

        # Second user with strict funnel drop off, but completed the step events for a normal funnel
        p2 = _create_person(distinct_ids=["user_2"], team=self.team, properties={"foo": "bar"})
        _create_event(
            event="$pageview",
            distinct_id="user_2",
            team=self.team,
            timestamp=timezone.now(),
            properties={"$session_id": "s3", "$window_id": "w1"},
            event_uuid="51111111-1111-1111-1111-111111111111",
        )
        _create_event(
            event="insight loaded",  # Interupting event
            distinct_id="user_2",
            team=self.team,
            timestamp=(timezone.now() + timedelta(minutes=3)),
            properties={"$session_id": "s3", "$window_id": "w2"},
            event_uuid="61111111-1111-1111-1111-111111111111",
        )
        _create_event(
            event="insight analyzed",
            distinct_id="user_2",
            team=self.team,
            timestamp=(timezone.now() + timedelta(minutes=4)),
            properties={"$session_id": "s3", "$window_id": "w2"},
            event_uuid="71111111-1111-1111-1111-111111111111",
        )
        timestamp1 = datetime(2021, 1, 2, 0, 0, 0)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s3",
            distinct_id="user_2",
            first_timestamp=timestamp1,
            last_timestamp=timestamp1,
        )

        # Success filter
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "date_from": "2021-01-01",
                "date_to": "2021-01-08",
                "funnel_order_type": "strict",
                "funnel_correlation_type": "properties",
                "events": [
                    {"id": "$pageview", "order": 0},
                    {"id": "insight analyzed", "order": 1},
                ],
                "include_recordings": "true",
                "funnel_correlation_property_values": [
                    {
                        "key": "foo",
                        "value": "bar",
                        "operator": "exact",
                        "type": "person",
                    }
                ],
                "funnel_correlation_person_converted": "True",
            }
        )
        _, results, _ = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], p1.uuid)
        self.assertEqual(
            results[0]["matched_recordings"],
            [
                {
                    "events": [
                        {
                            "timestamp": timezone.now() + timedelta(minutes=3),
                            "uuid": UUID("31111111-1111-1111-1111-111111111111"),
                            "window_id": "w2",
                        }
                    ],
                    "session_id": "s2",
                }
            ],
        )

        # Drop off filter
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "date_from": "2021-01-01",
                "date_to": "2021-01-08",
                "funnel_order_type": "strict",
                "funnel_correlation_type": "properties",
                "events": [
                    {"id": "$pageview", "order": 0},
                    {"id": "insight analyzed", "order": 1},
                ],
                "include_recordings": "true",
                "funnel_correlation_property_values": [
                    {
                        "key": "foo",
                        "value": "bar",
                        "operator": "exact",
                        "type": "person",
                    }
                ],
                "funnel_correlation_person_converted": "False",
            }
        )
        _, results, _ = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertEqual(results[0]["id"], p2.uuid)
        self.assertEqual(
            results[0]["matched_recordings"],
            [
                {
                    "events": [
                        {
                            "timestamp": timezone.now(),
                            "uuid": UUID("51111111-1111-1111-1111-111111111111"),
                            "window_id": "w1",
                        }
                    ],
                    "session_id": "s3",
                }
            ],
        )
