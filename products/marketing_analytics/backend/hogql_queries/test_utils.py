from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3

from products.marketing_analytics.backend.hogql_queries.utils import convert_team_conversion_goals_to_objects

EVENTS_NODE_GOAL_WITH_DW_FIELDS: dict[str, Any] = {
    "kind": "EventsNode",
    "conversion_goal_id": "goal-1",
    "conversion_goal_name": "Signup",
    "schema_map": {},
    "event": "signup",
    # data-warehouse-only fields that must not reach ConversionGoalFilter1 (extra="forbid")
    "table_name": "stripe_charges",
    "id_field": "id",
    "timestamp_field": "created_at",
    "distinct_id_field": "customer_id",
}

ACTIONS_NODE_GOAL: dict[str, Any] = {
    "kind": "ActionsNode",
    "conversion_goal_id": "goal-2",
    "conversion_goal_name": "Did action",
    "id": 42,
    "schema_map": {},
    "event": "$pageview",
}

DATA_WAREHOUSE_NODE_GOAL: dict[str, Any] = {
    "kind": "DataWarehouseNode",
    "conversion_goal_id": "goal-3",
    "conversion_goal_name": "Purchased",
    "id": "7",
    "table_name": "stripe_charges",
    "id_field": "id",
    "timestamp_field": "created_at",
    "distinct_id_field": "customer_id",
    "schema_map": {},
    "event": "ignored",
}

DATA_WAREHOUSE_NODE_GOAL_WITHOUT_ID_FIELD: dict[str, Any] = {
    "kind": "DataWarehouseNode",
    "conversion_goal_id": "goal-4",
    "conversion_goal_name": "Purchased",
    "id": "7",
    "table_name": "stripe_charges",
    "timestamp_field": "created_at",
    "distinct_id_field": "customer_id",
    "schema_map": {},
}


class TestConvertTeamConversionGoalsToObjects(BaseTest):
    @parameterized.expand(
        [
            ("events_node_with_dw_fields", EVENTS_NODE_GOAL_WITH_DW_FIELDS, ConversionGoalFilter1),
            ("actions_node", ACTIONS_NODE_GOAL, ConversionGoalFilter2),
            ("data_warehouse_node", DATA_WAREHOUSE_NODE_GOAL, ConversionGoalFilter3),
            (
                "data_warehouse_node_without_id_field",
                DATA_WAREHOUSE_NODE_GOAL_WITHOUT_ID_FIELD,
                ConversionGoalFilter3,
            ),
        ]
    )
    def test_converts_goal_to_expected_filter(self, _name, goal, expected_type):
        result = convert_team_conversion_goals_to_objects([goal], self.team.pk)

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], expected_type)
        self.assertEqual(result[0].conversion_goal_id, goal["conversion_goal_id"])

    def test_data_warehouse_node_derives_id_field_from_distinct_id_field(self):
        result = convert_team_conversion_goals_to_objects([DATA_WAREHOUSE_NODE_GOAL_WITHOUT_ID_FIELD], self.team.pk)

        self.assertEqual(len(result), 1)
        goal = result[0]
        assert isinstance(goal, ConversionGoalFilter3)
        self.assertEqual(goal.id_field, DATA_WAREHOUSE_NODE_GOAL_WITHOUT_ID_FIELD["distinct_id_field"])
        self.assertEqual(goal.distinct_id_field, DATA_WAREHOUSE_NODE_GOAL_WITHOUT_ID_FIELD["distinct_id_field"])

    def test_events_node_drops_data_warehouse_fields(self):
        result = convert_team_conversion_goals_to_objects([EVENTS_NODE_GOAL_WITH_DW_FIELDS], self.team.pk)

        self.assertEqual(len(result), 1)
        goal = result[0]
        assert isinstance(goal, ConversionGoalFilter1)
        self.assertEqual(goal.event, "signup")
        self.assertFalse(hasattr(goal, "table_name"))
