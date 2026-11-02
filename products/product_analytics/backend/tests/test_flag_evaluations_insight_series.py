from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import time_machine
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_flag_evaluations,
    _create_person,
    create_person_id_override_by_distinct_id,
    flush_persons_and_events,
)
from unittest.mock import patch

from parameterized import parameterized
from pydantic import BaseModel

from posthog.schema import (
    BaseMathType,
    BreakdownFilter,
    BreakdownType,
    CohortPropertyFilter,
    DataWarehouseNode,
    DataWarehousePropertyFilter,
    DateRange,
    EventsNode,
    FilterLogicalOperator,
    FunnelsDataWarehouseNode,
    FunnelsFilter,
    FunnelsQuery,
    HogQLQueryModifiers,
    IntervalType,
    LifecycleDataWarehouseNode,
    LifecycleQuery,
    PersonsOnEventsMode,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
    RetentionQuery,
    RetentionType,
    StickinessQuery,
    TimeWindowMode,
    TrendsQuery,
)

from posthog.hogql.database.schema.flag_evaluations import FLAG_EVALUATIONS_HOGQL_TABLE

from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL
from posthog.models.group.util import create_group
from posthog.models.person import Person

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import insert_static_cohort
from products.product_analytics.backend.facade.queries import (
    FunnelsQueryRunner,
    LifecycleQueryRunner,
    RetentionQueryRunner,
    StickinessQueryRunner,
    TrendsQueryRunner,
)

TABLE = FLAG_EVALUATIONS_HOGQL_TABLE
NOW = datetime(2025, 1, 10, 12, 0, tzinfo=UTC)
DATE_RANGE = DateRange(date_from="2025-01-08", date_to="2025-01-10")
IN_DATE_RANGE = datetime(2025, 1, 8, 8, 0, tzinfo=UTC)
BEFORE_DATE_RANGE = datetime(2024, 12, 1, tzinfo=UTC)
PROBE_FLAG = DataWarehousePropertyFilter(key="flag_key", operator=PropertyOperator.EXACT, value="probe-flag")
EXCLUDED_PEOPLE = ("dave", "erin", "frank", "gina")


def _flag_calls_series(**kwargs: Any) -> DataWarehouseNode:
    return DataWarehouseNode(
        id=TABLE,
        table_name=TABLE,
        timestamp_field="timestamp",
        distinct_id_field="distinct_id",
        id_field="uuid",
        **kwargs,
    )


def _aggregation_target(aggregation_group_type_index: int | None) -> str:
    return "person_id" if aggregation_group_type_index is None else f"$group_{aggregation_group_type_index}"


def _created_at_field(aggregation_group_type_index: int | None) -> str:
    return (
        "person.created_at"
        if aggregation_group_type_index is None
        else f"group_{aggregation_group_type_index}.created_at"
    )


def _retention_entity(aggregation_target_field: str) -> dict[str, Any]:
    return {
        "id": TABLE,
        "name": TABLE,
        "type": "data_warehouse",
        "table_name": TABLE,
        "timestamp_field": "timestamp",
        "aggregation_target_field": aggregation_target_field,
    }


def _flag_calls_funnel_step(aggregation_target_field: str = "person_id") -> FunnelsDataWarehouseNode:
    return FunnelsDataWarehouseNode(
        id=TABLE,
        table_name=TABLE,
        timestamp_field="timestamp",
        id_field="uuid",
        aggregation_target_field=aggregation_target_field,
        properties=[PROBE_FLAG],
    )


def _flag_calls_lifecycle_series(aggregation_group_type_index: int | None = None) -> LifecycleDataWarehouseNode:
    return LifecycleDataWarehouseNode(
        id=TABLE,
        table_name=TABLE,
        timestamp_field="timestamp",
        aggregation_target_field=_aggregation_target(aggregation_group_type_index),
        created_at_field=_created_at_field(aggregation_group_type_index),
    )


def _flag_calls_retention(
    aggregation_group_type_index: int | None = None,
    returning_entity: dict[str, Any] | None = None,
    **retention_filter: Any,
) -> RetentionQuery:
    flag_calls = _retention_entity(_aggregation_target(aggregation_group_type_index))
    return RetentionQuery(
        dateRange=DATE_RANGE,
        aggregation_group_type_index=aggregation_group_type_index,
        retentionFilter={
            "period": "Day",
            "totalIntervals": 3,
            "targetEntity": flag_calls,
            "returningEntity": returning_entity or flag_calls,
            **retention_filter,
        },
    )


@time_machine.travel(NOW, tick=False)
class TestFlagEvaluationsInsightSeries(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        table_gate = patch(
            "products.feature_flags.backend.facade.flags.is_flag_evaluations_table_enabled", return_value=True
        )
        table_gate.start()
        self.addCleanup(table_gate.stop)
        alice = self.alice = _create_person(team_id=self.team.pk, distinct_ids=["alice"], created_at=IN_DATE_RANGE)
        bob = _create_person(team_id=self.team.pk, distinct_ids=["bob"], created_at=IN_DATE_RANGE)
        alice_2 = _create_person(team_id=self.team.pk, distinct_ids=["alice-2"], created_at=IN_DATE_RANGE)
        self.bob_uuid = bob.uuid
        for distinct_id, person, flag_key, response, occurred_at, properties in [
            (
                "alice",
                alice,
                "probe-flag",
                "test",
                datetime(2025, 1, 8, 10, tzinfo=UTC),
                {"$session_id": "s-alice", "$group_0": "org-a"},
            ),
            (
                "alice",
                alice,
                "probe-flag",
                "test",
                datetime(2025, 1, 8, 11, tzinfo=UTC),
                {"$session_id": "s-alice", "$group_0": "org-a"},
            ),
            (
                "bob",
                bob,
                "probe-flag",
                "control",
                datetime(2025, 1, 8, 12, tzinfo=UTC),
                {"$session_id": "s-bob", "$group_0": "org-b"},
            ),
            ("bob", bob, "other-flag", "true", datetime(2025, 1, 9, 9, tzinfo=UTC), {}),
            # The row stores the person alice-2 had before the merge. Only the override makes it alice's call.
            (
                "alice-2",
                alice_2,
                "probe-flag",
                "test",
                datetime(2025, 1, 8, 13, tzinfo=UTC),
                {"$session_id": "s-alice-2"},
            ),
        ]:
            self._create_flag_call(distinct_id, person, flag_key, response, occurred_at, properties)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="alice",
            timestamp=datetime(2025, 1, 9, 10, tzinfo=UTC),
            properties={"$group_0": "org-a", "$session_id": "s-alice"},
        )
        flush_persons_and_events()
        create_person_id_override_by_distinct_id("alice-2", "alice", self.team.pk, version=1)

    def _create_flag_call(
        self,
        distinct_id: str,
        person: Person,
        flag_key: str,
        response: str,
        occurred_at: datetime,
        properties: dict[str, str],
    ) -> None:
        _create_flag_evaluations(
            self.team.pk,
            flag_key,
            timestamp=occurred_at,
            distinct_id=distinct_id,
            person_id=person.uuid,
            person_created_at=person.created_at,
            response=response,
            properties=properties,
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id=distinct_id,
            timestamp=occurred_at,
            properties={**properties, "$feature_flag": flag_key, "$feature_flag_response": response},
        )

    @parameterized.expand(
        [
            ("total_calls", BaseMathType.TOTAL, {"test": 3, "control": 1, BREAKDOWN_NULL_STRING_LABEL: 1}),
            ("unique_users", BaseMathType.DAU, {"test": 1, "control": 1, BREAKDOWN_NULL_STRING_LABEL: 1}),
            ("unique_sessions", BaseMathType.UNIQUE_SESSION, {"test": 2, "control": 1, BREAKDOWN_NULL_STRING_LABEL: 1}),
        ]
    )
    def test_trend_by_variant(self, _name: str, math: BaseMathType, expected: dict[str, int]):
        _create_flag_evaluations(
            self.team.pk,
            "probe-flag",
            timestamp=datetime(2025, 1, 8, 14, tzinfo=UTC),
            distinct_id="bob",
            person_id=self.bob_uuid,
            response=None,
            properties={"$session_id": "s-bob", "$group_0": "org-b"},
        )
        query = TrendsQuery(
            dateRange=DATE_RANGE,
            interval=IntervalType.DAY,
            series=[_flag_calls_series(math=math, properties=[PROBE_FLAG])],
            breakdownFilter=BreakdownFilter(breakdown_type=BreakdownType.DATA_WAREHOUSE, breakdown="response"),
        )

        results = TrendsQueryRunner(query=query, team=self.team).calculate().results

        assert {r["breakdown_value"]: r["count"] for r in results} == expected

    @parameterized.expand(
        [
            ("by_person", None, None, [2, 1]),
            ("by_group", 0, None, [2, 1]),
            ("by_session", None, "properties.$session_id", [3, 1]),
        ]
    )
    def test_funnel_from_flag_call_to_pageview(
        self,
        _name: str,
        aggregation_group_type_index: int | None,
        aggregate_by_hogql: str | None,
        expected: list[int],
    ):
        query = FunnelsQuery(
            dateRange=DATE_RANGE,
            aggregation_group_type_index=aggregation_group_type_index,
            funnelsFilter=FunnelsFilter(funnelAggregateByHogQL=aggregate_by_hogql),
            series=[
                _flag_calls_funnel_step(aggregate_by_hogql or _aggregation_target(aggregation_group_type_index)),
                EventsNode(event="$pageview"),
            ],
        )

        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        assert [step["count"] for step in results] == expected

    @parameterized.expand(
        [
            ("flag_calls_return_as_flag_calls", None, None, [2, 1, 0]),
            (
                "flag_calls_return_as_pageviews",
                None,
                {"id": "$pageview", "name": "$pageview", "type": "events"},
                [2, 1, 0],
            ),
            ("by_group", 0, None, [2, 0, 0]),
        ]
    )
    def test_retention(
        self,
        _name: str,
        aggregation_group_type_index: int | None,
        returning_event: dict[str, Any] | None,
        expected: list[int],
    ):
        query = _flag_calls_retention(aggregation_group_type_index, returning_entity=returning_event)

        results = RetentionQueryRunner(query=query, team=self.team).calculate().model_dump()["results"]

        assert [value["count"] for value in results[0]["values"]] == expected

    def test_stickiness(self):
        query = StickinessQuery(dateRange=DATE_RANGE, interval=IntervalType.DAY, series=[_flag_calls_series()])

        results = StickinessQueryRunner(query=query, team=self.team).calculate().results

        assert results[0]["data"] == [1, 1, 0]

    @parameterized.expand(
        [
            (
                "by_person",
                None,
                {"new": [2, 0, 0], "returning": [0, 1, 0], "resurrecting": [0, 1, 0], "dormant": [0, -1, -2]},
            ),
            (
                "by_group",
                0,
                {"new": [1, 0, 0], "returning": [0, 0, 0], "resurrecting": [1, 1, 0], "dormant": [0, -2, -1]},
            ),
        ]
    )
    def test_lifecycle_matches_events(
        self,
        _name: str,
        aggregation_group_type_index: int | None,
        expected: dict[str, list[int]],
    ):
        for group_key, group_created_at in [
            ("org-a", IN_DATE_RANGE),
            ("org-b", BEFORE_DATE_RANGE),
            ("org-c", BEFORE_DATE_RANGE),
        ]:
            create_group(team_id=self.team.pk, group_type_index=0, group_key=group_key, timestamp=group_created_at)
        # Carol, org-b and org-c predate the date range, so their first call in it makes them resurrecting, not new.
        # Bob, org-b's only caller, was created in the range, so org-b reads new if by_group uses person creation time.
        carol = _create_person(team_id=self.team.pk, distinct_ids=["carol"], created_at=BEFORE_DATE_RANGE)
        self._create_flag_call(
            "carol",
            carol,
            "other-flag",
            "true",
            datetime(2025, 1, 9, 12, tzinfo=UTC),
            {"$group_0": "org-c"},
        )
        # Lifecycle excludes both personless calls. Events lifecycle also drops a force-upgraded call, because that
        # call carries $process_person_profile=false. Counting either call would add an active user or group on
        # 2025-01-08.
        for person_mode in ["propertyless", "force_upgrade"]:
            _create_flag_evaluations(
                self.team.pk,
                "probe-flag",
                timestamp=datetime(2025, 1, 8, 14, tzinfo=UTC),
                distinct_id="anonymous",
                person_mode=person_mode,
                properties={"$process_person_profile": False, "$group_0": "org-c"},
            )
        query = LifecycleQuery(
            dateRange=DATE_RANGE,
            interval=IntervalType.DAY,
            aggregation_group_type_index=aggregation_group_type_index,
            # This mode reads the person creation time stored on the row and the merge-corrected person, as
            # flag_evaluations does.
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
            series=[_flag_calls_lifecycle_series(aggregation_group_type_index)],
        )
        events_query = query.model_copy(update={"series": [EventsNode(event="$feature_flag_called")]})

        with self.capture_select_queries() as queries:
            results = LifecycleQueryRunner(query=query, team=self.team).calculate().results
        events_results = LifecycleQueryRunner(query=events_query, team=self.team).calculate().results

        lifecycle = {r["status"]: r["data"] for r in results}
        assert lifecycle == expected
        assert lifecycle == {r["status"]: r["data"] for r in events_results}
        # A filter on properties.$process_person_profile keeps the same rows. Only the SQL shows that the query reads
        # the person_mode column instead of parsing the properties JSON of every row.
        [sql] = [captured for captured in queries if "flag_evaluations" in captured]
        assert "person_mode" in sql
        assert "JSONExtractRaw" not in sql

    @parameterized.expand(
        [
            (
                "trends",
                TrendsQueryRunner,
                TrendsQuery(
                    dateRange=DATE_RANGE,
                    interval=IntervalType.DAY,
                    series=[_flag_calls_series(math=BaseMathType.TOTAL, properties=[PROBE_FLAG])],
                    breakdownFilter=BreakdownFilter(breakdown_type=BreakdownType.DATA_WAREHOUSE, breakdown="response"),
                ),
                lambda results: {r["breakdown_value"]: r["count"] for r in results},
                {"test": 3, "control": 1},
            ),
            (
                "funnels",
                FunnelsQueryRunner,
                FunnelsQuery(
                    dateRange=DATE_RANGE,
                    series=[_flag_calls_funnel_step(), EventsNode(event="$pageview")],
                ),
                lambda results: [step["count"] for step in results],
                [2, 1],
            ),
            (
                "retention_fixed_intervals",
                RetentionQueryRunner,
                _flag_calls_retention(),
                lambda results: [value["count"] for value in results[0]["values"]],
                [2, 1, 0],
            ),
            (
                "retention_24_hour_windows",
                RetentionQueryRunner,
                _flag_calls_retention(timeWindowMode=TimeWindowMode.FIELD_24_HOUR_WINDOWS),
                lambda results: [value["count"] for value in results[0]["values"]],
                [2, 0, 0],
            ),
            (
                "retention_first_time_fixed_intervals",
                RetentionQueryRunner,
                _flag_calls_retention(retentionType=RetentionType.RETENTION_FIRST_TIME),
                lambda results: [value["count"] for value in results[0]["values"]],
                [2, 1, 0],
            ),
            (
                "retention_first_time_24_hour_windows",
                RetentionQueryRunner,
                _flag_calls_retention(
                    retentionType=RetentionType.RETENTION_FIRST_TIME,
                    timeWindowMode=TimeWindowMode.FIELD_24_HOUR_WINDOWS,
                ),
                lambda results: [value["count"] for value in results[0]["values"]],
                [2, 0, 0],
            ),
            (
                "stickiness",
                StickinessQueryRunner,
                StickinessQuery(dateRange=DATE_RANGE, interval=IntervalType.DAY, series=[_flag_calls_series()]),
                lambda results: results[0]["data"],
                [1, 1, 0],
            ),
            (
                "lifecycle",
                LifecycleQueryRunner,
                LifecycleQuery(
                    dateRange=DATE_RANGE,
                    interval=IntervalType.DAY,
                    series=[_flag_calls_lifecycle_series()],
                ),
                lambda results: {r["status"]: r["data"] for r in results},
                {"new": [2, 0, 0], "returning": [0, 1, 0], "resurrecting": [0, 0, 0], "dormant": [0, -1, -1]},
            ),
        ]
    )
    def test_filters_drop_excluded_people(
        self,
        _name: str,
        runner_class: type[QueryRunner],
        query: BaseModel,
        read_results: Callable[[list[Any]], Any],
        expected: Any,
    ):
        people = {name: _create_person(team_id=self.team.pk, distinct_ids=[name]) for name in EXCLUDED_PEOPLE}
        flush_persons_and_events()
        for name, properties, person_properties in [
            ("dave", {"$host": "localhost:8000"}, None),
            ("erin", None, {"email": "erin@posthog.com"}),
            ("frank", None, None),
            ("gina", None, None),
        ]:
            _create_flag_evaluations(
                self.team.pk,
                "probe-flag",
                timestamp=datetime(2025, 1, 8, 14, tzinfo=UTC),
                distinct_id=name,
                person_id=people[name].uuid,
                response="test",
                properties=properties,
                person_properties=person_properties,
            )
        # Alice's first calls pass every filter. Her return call does not, so only a scan that drops it keeps her
        # out of the later retention intervals.
        self._create_flag_call(
            "alice", self.alice, "other-flag", "true", datetime(2025, 1, 9, 10, tzinfo=UTC), {"$host": "localhost:8000"}
        )
        test_account_cohort = Cohort.objects.create(team=self.team, is_static=True)
        insert_static_cohort([people["frank"].uuid], test_account_cohort.pk, team_id=self.team.pk)
        global_filter_cohort = Cohort.objects.create(team=self.team, is_static=True)
        insert_static_cohort([people["gina"].uuid], global_filter_cohort.pk, team_id=self.team.pk)
        self.team.test_account_filters = [
            {"key": "$host", "operator": "is_not", "value": ["localhost:8000"], "type": "event"},
            {"key": "email", "operator": "not_icontains", "value": "posthog.com", "type": "person"},
            {"key": "id", "operator": "not_in", "value": test_account_cohort.pk, "type": "cohort"},
        ]
        self.team.save()
        filtered_query = query.model_copy(
            deep=True,
            update={
                "filterTestAccounts": True,
                "properties": PropertyGroupFilter(
                    type=FilterLogicalOperator.AND_,
                    values=[
                        PropertyGroupFilterValue(
                            type=FilterLogicalOperator.AND_,
                            values=[
                                CohortPropertyFilter(value=global_filter_cohort.pk, operator=PropertyOperator.NOT_IN)
                            ],
                        )
                    ],
                ),
            },
        )

        response = runner_class(query=filtered_query, team=self.team).calculate()

        assert read_results(response.model_dump()["results"]) == expected
