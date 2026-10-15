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

from posthog.schema import (
    BaseMathType,
    BreakdownFilter,
    BreakdownType,
    DataWarehouseNode,
    DataWarehousePropertyFilter,
    DateRange,
    EventsNode,
    FunnelsDataWarehouseNode,
    FunnelsFilter,
    FunnelsQuery,
    HogQLQueryModifiers,
    IntervalType,
    LifecycleDataWarehouseNode,
    LifecycleQuery,
    PersonsOnEventsMode,
    PropertyOperator,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
)

from posthog.hogql.database.schema.flag_evaluations import FLAG_EVALUATIONS_HOGQL_TABLE

from posthog.models.group.util import create_group
from posthog.models.person import Person

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


@time_machine.travel(NOW, tick=False)
class TestFlagEvaluationsInsightSeries(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        table_gate = patch(
            "products.feature_flags.backend.facade.flags.is_flag_evaluations_table_enabled", return_value=True
        )
        table_gate.start()
        self.addCleanup(table_gate.stop)
        alice = _create_person(team_id=self.team.pk, distinct_ids=["alice"], created_at=IN_DATE_RANGE)
        bob = _create_person(team_id=self.team.pk, distinct_ids=["bob"], created_at=IN_DATE_RANGE)
        alice_2 = _create_person(team_id=self.team.pk, distinct_ids=["alice-2"], created_at=IN_DATE_RANGE)
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
            ("total_calls", BaseMathType.TOTAL, {"test": 3, "control": 1}),
            ("unique_users", BaseMathType.DAU, {"test": 1, "control": 1}),
            ("unique_sessions", BaseMathType.UNIQUE_SESSION, {"test": 2, "control": 1}),
        ]
    )
    def test_trend_by_variant(self, _name: str, math: BaseMathType, expected: dict[str, int]):
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
                FunnelsDataWarehouseNode(
                    id=TABLE,
                    table_name=TABLE,
                    timestamp_field="timestamp",
                    id_field="uuid",
                    aggregation_target_field=aggregate_by_hogql or _aggregation_target(aggregation_group_type_index),
                    properties=[PROBE_FLAG],
                ),
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
        flag_calls = _retention_entity(_aggregation_target(aggregation_group_type_index))
        query = RetentionQuery(
            dateRange=DATE_RANGE,
            aggregation_group_type_index=aggregation_group_type_index,
            retentionFilter={
                "period": "Day",
                "totalIntervals": 3,
                "targetEntity": flag_calls,
                "returningEntity": returning_event or flag_calls,
            },
        )

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
        # Lifecycle excludes this personless call. Counting it would add an active user or group on 2025-01-08.
        _create_flag_evaluations(
            self.team.pk,
            "probe-flag",
            timestamp=datetime(2025, 1, 8, 14, tzinfo=UTC),
            distinct_id="anonymous",
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
            series=[
                LifecycleDataWarehouseNode(
                    id=TABLE,
                    table_name=TABLE,
                    timestamp_field="timestamp",
                    aggregation_target_field=_aggregation_target(aggregation_group_type_index),
                    created_at_field=_created_at_field(aggregation_group_type_index),
                )
            ],
        )
        events_query = query.model_copy(update={"series": [EventsNode(event="$feature_flag_called")]})

        results = LifecycleQueryRunner(query=query, team=self.team).calculate().results
        events_results = LifecycleQueryRunner(query=events_query, team=self.team).calculate().results

        lifecycle = {r["status"]: r["data"] for r in results}
        assert lifecycle == expected
        assert lifecycle == {r["status"]: r["data"] for r in events_results}
