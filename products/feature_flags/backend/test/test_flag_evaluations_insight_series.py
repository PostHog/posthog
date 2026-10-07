import uuid
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
    FunnelsQuery,
    IntervalType,
    LifecycleDataWarehouseNode,
    LifecycleQuery,
    PropertyOperator,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
)

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig
from products.product_analytics.backend.facade.queries import (
    FunnelsQueryRunner,
    LifecycleQueryRunner,
    RetentionQueryRunner,
    StickinessQueryRunner,
    TrendsQueryRunner,
)

TABLE = "posthog.flag_evaluations"
NOW = datetime(2025, 1, 10, 12, 0, tzinfo=UTC)
DATE_RANGE = DateRange(date_from="2025-01-08", date_to="2025-01-10")
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


def _retention_entity(aggregation_target_field: str = "person_id") -> dict[str, Any]:
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
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization,
            defaults={"flag_evaluations_mode": FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY},
        )
        person_created_at = datetime(2025, 1, 8, 8, 0, tzinfo=UTC)
        alice = _create_person(team_id=self.team.pk, distinct_ids=["alice"], created_at=person_created_at)
        bob = _create_person(team_id=self.team.pk, distinct_ids=["bob"], created_at=person_created_at)
        for distinct_id, person_id, flag_key, response, occurred_at, properties in [
            (
                "alice",
                alice.uuid,
                "probe-flag",
                "test",
                datetime(2025, 1, 8, 10, tzinfo=UTC),
                {"$session_id": "s-alice", "$group_0": "org-a"},
            ),
            (
                "alice",
                alice.uuid,
                "probe-flag",
                "test",
                datetime(2025, 1, 8, 11, tzinfo=UTC),
                {"$session_id": "s-alice", "$group_0": "org-a"},
            ),
            (
                "bob",
                bob.uuid,
                "probe-flag",
                "control",
                datetime(2025, 1, 8, 12, tzinfo=UTC),
                {"$session_id": "s-bob", "$group_0": "org-b"},
            ),
            ("bob", bob.uuid, "other-flag", "true", datetime(2025, 1, 9, 9, tzinfo=UTC), {}),
            # The row stores the person alice-2 had before the merge. Only the override makes it alice's call.
            (
                "alice-2",
                uuid.uuid4(),
                "probe-flag",
                "test",
                datetime(2025, 1, 8, 13, tzinfo=UTC),
                {"$session_id": "s-alice-2"},
            ),
        ]:
            _create_flag_evaluations(
                self.team.pk,
                flag_key,
                timestamp=occurred_at,
                distinct_id=distinct_id,
                person_id=person_id,
                response=response,
                properties=properties,
            )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="alice",
            timestamp=datetime(2025, 1, 9, 10, tzinfo=UTC),
            properties={"$group_0": "org-a"},
        )
        flush_persons_and_events()
        create_person_id_override_by_distinct_id("alice-2", "alice", self.team.pk, version=1)

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
            ("by_person", None, "person_id"),
            ("by_group", 0, "$group_0"),
        ]
    )
    def test_funnel_from_flag_call_to_pageview(
        self, _name: str, aggregation_group_type_index: int | None, aggregation_target_field: str
    ):
        query = FunnelsQuery(
            dateRange=DATE_RANGE,
            aggregation_group_type_index=aggregation_group_type_index,
            series=[
                FunnelsDataWarehouseNode(
                    id=TABLE,
                    table_name=TABLE,
                    timestamp_field="timestamp",
                    id_field="uuid",
                    aggregation_target_field=aggregation_target_field,
                    properties=[PROBE_FLAG],
                ),
                EventsNode(event="$pageview"),
            ],
        )

        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        assert [step["count"] for step in results] == [2, 1]

    @parameterized.expand(
        [
            ("flag_calls_return_as_flag_calls", None, "person_id", _retention_entity(), [2, 1, 0]),
            (
                "flag_calls_return_as_pageviews",
                None,
                "person_id",
                {"id": "$pageview", "name": "$pageview", "type": "events"},
                [2, 1, 0],
            ),
            ("by_group", 0, "$group_0", _retention_entity("$group_0"), [2, 0, 0]),
        ]
    )
    def test_retention(
        self,
        _name: str,
        aggregation_group_type_index: int | None,
        aggregation_target_field: str,
        returning_entity: dict[str, Any],
        expected: list[int],
    ):
        query = RetentionQuery(
            dateRange=DATE_RANGE,
            aggregation_group_type_index=aggregation_group_type_index,
            retentionFilter={
                "period": "Day",
                "totalIntervals": 3,
                "targetEntity": _retention_entity(aggregation_target_field),
                "returningEntity": returning_entity,
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
                "person_id",
                {"new": [2, 0, 0], "returning": [0, 1, 0], "resurrecting": [0, 0, 0], "dormant": [0, -1, -1]},
            ),
            (
                "by_group",
                0,
                "$group_0",
                {"new": [2, 0, 0], "returning": [0, 0, 0], "resurrecting": [0, 0, 0], "dormant": [0, -2, 0]},
            ),
        ]
    )
    def test_lifecycle(
        self,
        _name: str,
        aggregation_group_type_index: int | None,
        aggregation_target_field: str,
        expected: dict[str, list[int]],
    ):
        query = LifecycleQuery(
            dateRange=DATE_RANGE,
            interval=IntervalType.DAY,
            aggregation_group_type_index=aggregation_group_type_index,
            series=[
                LifecycleDataWarehouseNode(
                    id=TABLE,
                    table_name=TABLE,
                    timestamp_field="timestamp",
                    aggregation_target_field=aggregation_target_field,
                    created_at_field="timestamp",
                )
            ],
        )

        results = LifecycleQueryRunner(query=query, team=self.team).calculate().results

        assert {r["status"]: r["data"] for r in results} == expected
