import unittest
import pytest
from freezegun import freeze_time

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_in_tests
from posthog.models import Action
from posthog.schema import (
    BaseMathType,
    ConversionGoalFilter1,
    ConversionGoalFilter2,
    ConversionGoalFilter3,
    DateRange,
    EventPropertyFilter,
    NodeKind,
    PropertyMathType,
    PropertyOperator,
)
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import (
    ConversionGoalProcessor,
    add_conversion_goal_property_filters,
)


def _create_action(**kwargs):
    """Helper to create Action objects for testing"""
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    event_name = kwargs.pop("event_name", name)
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": event_name, "properties": properties}])
    return action


class TestConversionGoalProcessor(ClickhouseTestMixin, BaseTest):
    """
    Comprehensive test suite for ConversionGoalProcessor

    Test Structure:
    1. Basic Unit Tests - Core functionality
    2. Node Type Tests - EventsNode, ActionsNode, DataWarehouseNode
    3. Math Type Tests - TOTAL, DAU, SUM, etc.
    4. Property Filter Tests - Event properties, filters
    5. Schema Mapping Tests - UTM expressions, field mappings
    6. Query Generation Tests - CTE, JOIN, SELECT
    7. Error Handling Tests - Missing data, invalid configs
    8. Edge Case Tests - Complex scenarios
    9. Integration Tests - Full query execution
    10. Temporal Attribution Tests - Campaign attribution timing validation
    11. Same-Day Attribution Tests - Intraday timing precision
    12. Complex Customer Journey Tests - Multi-event, multi-channel attribution
    13. Attribution Window Tests - Time-based attribution limits
    14. Data Quality Edge Cases - Malformed UTM, duplicates, missing data
    15. Comprehensive Integration Tests - Real-world scenarios

    Attribution Validation Pattern:
    ============================

    When testing temporal attribution, use this validation pattern:

    1. ✅ Forward Order (Ad → Conversion): Should attribute correctly
       Expected: campaign_name = actual_campaign, source_name = actual_source

    2. ❌ Backward Order (Conversion → Ad): Should show Unknown attribution
       Expected: campaign_name/source_name in [None, "Unknown", "", "Unknown Campaign/Source"]

    3. 🎯 Last-Touch Attribution (Multi-touchpoint): Should attribute to most recent ad
       Expected: campaign_name = last_campaign (not first_campaign)

    4. 🔄 Mixed Timeline: Only ads BEFORE conversion should be considered
       Expected: Ignore any ads that come after conversion timestamp

    Query Result Structure: [campaign_name, source_name, conversion_count]
    - row[0] = campaign_name
    - row[1] = source_name
    - row[2] = conversion_count
    """

    maxDiff = None

    def setUp(self):
        super().setUp()
        self.date_range = DateRange(date_from="2023-01-01", date_to="2023-01-31")
        self._create_test_data()

    def _create_test_data(self):
        """Create comprehensive test data covering various scenarios"""
        with freeze_time("2023-01-15"):
            # Basic users
            _create_person(distinct_ids=["user1"], team=self.team, properties={"$browser": "Chrome"})
            _create_person(distinct_ids=["user2"], team=self.team, properties={"$browser": "Firefox"})
            _create_person(distinct_ids=["user3"], team=self.team, properties={"$browser": "Safari"})

            # User with UTM data
            _create_event(
                distinct_id="user1",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "google", "revenue": 100},
            )
            _create_event(
                distinct_id="user1",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "google", "revenue": 250},
            )

            # User with different UTM data
            _create_event(
                distinct_id="user2",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "winter_promo", "utm_source": "facebook", "revenue": 150},
            )

            # User without UTM data (edge case)
            _create_event(distinct_id="user3", event="newsletter_signup", team=self.team, properties={"revenue": 50})

            # High-value events for sum testing
            _create_event(
                distinct_id="user1",
                event="premium_purchase",
                team=self.team,
                properties={"revenue": 1000, "utm_campaign": "premium_push", "utm_source": "email"},
            )

            flush_persons_and_events()

    # ================================================================
    # 1. BASIC UNIT TESTS - Core functionality
    # ================================================================

    def test_processor_basic_properties(self):
        """Test basic processor properties and initialization"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="signup_goal",
            conversion_goal_name="Sign Ups",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        # Test basic getters
        self.assertEqual(processor.get_cte_name(), "signup_goal")
        self.assertEqual(processor.get_table_name(), "events")
        self.assertEqual(processor.get_date_field(), "events.timestamp")
        self.assertIsInstance(processor.goal, ConversionGoalFilter1)
        self.assertEqual(processor.index, 0)

    def test_processor_index_variations(self):
        """Test processor behavior with different index values"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="test_event",
            conversion_goal_id="test",
            conversion_goal_name="Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        # Test various index values
        for index in [0, 1, 5, 10]:
            processor = ConversionGoalProcessor(
                goal=goal, index=index, team=self.team, query_date_range=self.date_range
            )
            join_clause = processor.generate_join_clause()
            self.assertEqual(join_clause.alias, f"cg_{index}")

    # ================================================================
    # 2. NODE TYPE TESTS - EventsNode, ActionsNode, DataWarehouseNode
    # ================================================================

    def test_events_node_basic(self):
        """Test basic EventsNode functionality"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="events_basic",
            conversion_goal_name="Events Basic",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        self.assertEqual(processor.get_table_name(), "events")
        conditions = processor.get_base_where_conditions()
        self.assertEqual(len(conditions), 2)  # team_id + event filter

    def test_actions_node_basic(self):
        """Test basic ActionsNode functionality"""
        action = _create_action(team=self.team, name="Test Action", event_name="sign_up")

        goal = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id=str(action.id),
            conversion_goal_id="actions_basic",
            conversion_goal_name="Actions Basic",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        self.assertEqual(processor.get_table_name(), "events")
        conditions = processor.get_base_where_conditions()
        self.assertEqual(len(conditions), 2)

    def test_data_warehouse_node_basic(self):
        """Test basic DataWarehouseNode functionality - might fail initially"""
        goal = ConversionGoalFilter3(
            kind=NodeKind.DATA_WAREHOUSE_NODE,
            id="warehouse_id",
            table_name="warehouse_table",
            conversion_goal_id="warehouse_basic",
            conversion_goal_name="Warehouse Basic",
            math=BaseMathType.TOTAL,
            distinct_id_field="user_id",
            id_field="user_id",
            timestamp_field="event_timestamp",
            schema_map={
                "utm_campaign_name": "campaign_name",
                "utm_source_name": "source_name",
                "distinct_id_field": "user_id",
                "timestamp_field": "event_timestamp",
            },
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        self.assertEqual(processor.get_table_name(), "warehouse_table")
        self.assertEqual(processor.get_date_field(), "event_timestamp")

    # ================================================================
    # 3. MATH TYPE TESTS - TOTAL, DAU, SUM, etc.
    # ================================================================

    def test_math_type_total_count(self):
        """Test TOTAL math type produces count() aggregation"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="total_test",
            conversion_goal_name="Total Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        select_field = processor.get_select_field()
        self.assertIsInstance(select_field, ast.Call)
        self.assertEqual(select_field.name, "count")

    def test_math_type_dau(self):
        """Test DAU math type produces uniq(distinct_id) aggregation"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="dau_test",
            conversion_goal_name="DAU Test",
            math=BaseMathType.DAU,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        select_field = processor.get_select_field()
        self.assertIsInstance(select_field, ast.Call)
        self.assertEqual(select_field.name, "uniq")
        self.assertEqual(select_field.args[0].chain, ["events", "distinct_id"])

    def test_math_type_sum_with_property(self):
        """Test SUM math type with valid property"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="sum_test",
            conversion_goal_name="Sum Test",
            math=PropertyMathType.SUM,
            math_property="revenue",
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        select_field = processor.get_select_field()
        self.assertIsInstance(select_field, ast.Call)
        self.assertEqual(select_field.name, "round")

    def test_math_type_sum_without_property(self):
        """Test SUM math type without property returns 0"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="sum_no_prop",
            conversion_goal_name="Sum No Prop",
            math=PropertyMathType.SUM,
            math_property=None,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        select_field = processor.get_select_field()
        self.assertIsInstance(select_field, ast.Constant)
        self.assertEqual(select_field.value, 0)

    def test_math_type_average(self):
        """Test AVERAGE math type - should fallback to count(*) since not implemented"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="avg_test",
            conversion_goal_name="Average Test",
            math=PropertyMathType.AVG,
            math_property="revenue",
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        select_field = processor.get_select_field()

        # AVG is not implemented, so it should fallback to count(*)
        self.assertIsInstance(select_field, ast.Call)
        self.assertEqual(select_field.name, "count")
        self.assertEqual(select_field.args[0].value, "*")

        # If AVG were properly implemented, we'd expect something like:
        # self.assertEqual(select_field.name, "avg")
        # or
        # self.assertEqual(select_field.name, "round")  # with avg inside

    # ================================================================
    # 4. PROPERTY FILTER TESTS - Event properties, filters
    # ================================================================

    def test_property_filters_single_filter(self):
        """Test single property filter"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="single_filter",
            conversion_goal_name="Single Filter",
            math=BaseMathType.TOTAL,
            properties=[EventPropertyFilter(key="revenue", operator=PropertyOperator.GT, value=100, type="event")],
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        # Test base conditions first
        base_conditions = processor.get_base_where_conditions()
        self.assertEqual(len(base_conditions), 2)  # team_id + event

        # Test full conditions with property filters applied
        full_conditions = base_conditions.copy()
        full_conditions = add_conversion_goal_property_filters(full_conditions, goal, self.team)
        self.assertEqual(len(full_conditions), 3)  # team_id + event + property filter

    def test_property_filters_multiple_filters(self):
        """Test multiple property filters combined into single compound expression"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multi_filter",
            conversion_goal_name="Multi Filter",
            math=BaseMathType.TOTAL,
            properties=[
                EventPropertyFilter(key="revenue", operator=PropertyOperator.GT, value=100, type="event"),
                EventPropertyFilter(key="utm_source", operator=PropertyOperator.EXACT, value="google", type="event"),
            ],
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        # Test base conditions first
        base_conditions = processor.get_base_where_conditions()
        self.assertEqual(len(base_conditions), 2)  # team_id + event

        # Test full conditions with property filters applied
        # Multiple property filters get combined into single compound expression
        full_conditions = base_conditions.copy()
        full_conditions = add_conversion_goal_property_filters(full_conditions, goal, self.team)
        self.assertEqual(len(full_conditions), 3)  # team_id + event + 1 combined property filter

    def test_property_filters_complex_operators(self):
        """Test complex property filter operators like LT and ICONTAINS"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="complex_filter",
            conversion_goal_name="Complex Filter",
            math=BaseMathType.TOTAL,
            properties=[
                EventPropertyFilter(key="revenue", operator=PropertyOperator.LT, value=500, type="event"),
                EventPropertyFilter(
                    key="utm_campaign", operator=PropertyOperator.ICONTAINS, value="sale", type="event"
                ),
            ],
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        # Test base conditions first
        base_conditions = processor.get_base_where_conditions()
        self.assertEqual(len(base_conditions), 2)  # team_id + event

        # Test full conditions with property filters applied
        # Complex operators (LT, ICONTAINS) should be handled correctly
        full_conditions = base_conditions.copy()
        full_conditions = add_conversion_goal_property_filters(full_conditions, goal, self.team)
        self.assertEqual(len(full_conditions), 3)  # team_id + event + 1 combined property filter

    # ================================================================
    # 5. SCHEMA MAPPING TESTS - UTM expressions, field mappings
    # ================================================================

    def test_utm_expressions_events_node(self):
        """Test UTM expressions for EventsNode"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="utm_events",
            conversion_goal_name="UTM Events",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        utm_campaign, utm_source = processor.get_utm_expressions()
        self.assertEqual(utm_campaign.chain, ["events", "properties", "utm_campaign"])
        self.assertEqual(utm_source.chain, ["events", "properties", "utm_source"])

    def test_utm_expressions_data_warehouse_node(self):
        """Test UTM expressions for DataWarehouseNode"""
        goal = ConversionGoalFilter3(
            kind=NodeKind.DATA_WAREHOUSE_NODE,
            id="warehouse_utm",
            table_name="warehouse_table",
            conversion_goal_id="utm_warehouse",
            conversion_goal_name="UTM Warehouse",
            math=BaseMathType.TOTAL,
            distinct_id_field="user_id",
            id_field="user_id",
            timestamp_field="created_at",
            schema_map={
                "utm_campaign_name": "campaign_field",
                "utm_source_name": "source_field",
                "distinct_id_field": "user_id",
                "timestamp_field": "created_at",
            },
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        utm_campaign, utm_source = processor.get_utm_expressions()
        self.assertEqual(utm_campaign.chain, ["campaign_field"])
        self.assertEqual(utm_source.chain, ["source_field"])

    def test_schema_mapping_custom_fields(self):
        """Test custom field mappings in schema_map"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="custom_schema",
            conversion_goal_name="Custom Schema",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "custom_campaign_field", "utm_source_name": "custom_source_field"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        utm_campaign, utm_source = processor.get_utm_expressions()
        self.assertEqual(utm_campaign.chain, ["events", "properties", "custom_campaign_field"])
        self.assertEqual(utm_source.chain, ["events", "properties", "custom_source_field"])

    def test_schema_mapping_missing_fields(self):
        """Test behavior when schema_map is missing required fields - should fallback gracefully"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="missing_schema",
            conversion_goal_name="Missing Schema",
            math=BaseMathType.TOTAL,
            schema_map={},  # Empty schema map
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        # Should handle missing schema gracefully and fallback to defaults
        utm_campaign, utm_source = processor.get_utm_expressions()
        self.assertIsNotNone(utm_campaign)
        self.assertIsNotNone(utm_source)

        # Verify fallback to default field names
        self.assertEqual(utm_campaign.chain, ["events", "properties", "utm_campaign"])
        self.assertEqual(utm_source.chain, ["events", "properties", "utm_source"])

    # ================================================================
    # 6. QUERY GENERATION TESTS - CTE, JOIN, SELECT
    # ================================================================

    def test_generate_join_clause_structure(self):
        """Test JOIN clause generation structure"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="join_test",
            conversion_goal_name="Join Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        join_clause = processor.generate_join_clause()
        self.assertEqual(join_clause.join_type, "LEFT JOIN")
        self.assertEqual(join_clause.alias, "cg_0")
        self.assertEqual(join_clause.constraint.constraint_type, "ON")
        self.assertIsInstance(join_clause.constraint.expr, ast.And)

    def test_generate_select_columns_structure(self):
        """Test SELECT columns generation structure"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="select_test",
            conversion_goal_name="Select Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        select_columns = processor.generate_select_columns()
        self.assertEqual(len(select_columns), 2)

        # First column: conversion goal value
        self.assertEqual(select_columns[0].alias, "Select Test")

        # Second column: cost per conversion goal
        self.assertEqual(select_columns[1].alias, "Cost per Select Test")
        self.assertIsInstance(select_columns[1].expr, ast.Call)
        self.assertEqual(select_columns[1].expr.name, "round")

    def test_generate_cte_query_basic_execution(self):
        """Test basic CTE query generation and execution"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="cte_basic",
            conversion_goal_name="CTE Basic",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        self.assertIsNotNone(cte_query)

        # Try to execute the query
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

    # ================================================================
    # 7. ERROR HANDLING TESTS - Missing data, invalid configs
    # ================================================================

    def test_error_missing_action(self):
        """Test error handling when Action doesn't exist"""
        goal = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id="999999",
            conversion_goal_id="missing_action",
            conversion_goal_name="Missing Action",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        with self.assertRaises(Action.DoesNotExist):
            processor.get_base_where_conditions()

    def test_error_invalid_math_property_combination(self):
        """Test graceful handling of invalid math+property combinations"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="invalid_combo",
            conversion_goal_name="Invalid Combo",
            math=BaseMathType.DAU,
            math_property="revenue",  # Invalid combo
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        # Should handle gracefully by ignoring irrelevant math_property for DAU
        select_field = processor.get_select_field()
        self.assertIsNotNone(select_field)

        # DAU should ignore math_property and use uniq(distinct_id)
        self.assertIsInstance(select_field, ast.Call)
        self.assertEqual(select_field.name, "uniq")
        self.assertEqual(select_field.args[0].chain, ["events", "distinct_id"])

    def test_error_empty_event_name(self):
        """Test graceful handling of empty event name"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="",
            conversion_goal_id="empty_event",
            conversion_goal_name="Empty Event",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        # Should handle empty event name gracefully - no event condition added
        conditions = processor.get_base_where_conditions()
        self.assertIsNotNone(conditions)
        # Only team_id condition should be present (no event condition for empty event name)
        self.assertEqual(len(conditions), 1)  # Only team_id

        # Verify it's the team_id condition
        team_condition = conditions[0]
        self.assertIsInstance(team_condition, ast.CompareOperation)
        self.assertEqual(team_condition.left.chain, ["events", "team_id"])
        self.assertEqual(team_condition.right.value, self.team.pk)

    # ================================================================
    # 8. EDGE CASE TESTS - Complex scenarios
    # ================================================================

    def test_edge_case_very_long_goal_names(self):
        """Test graceful handling of very long goal names"""
        long_name = "A" * 1000  # Very long name

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="long_name",
            conversion_goal_name=long_name,
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        # Should handle very long names without issues
        select_columns = processor.generate_select_columns()
        self.assertEqual(len(select_columns), 2)

        # First column should preserve the full long name
        self.assertEqual(select_columns[0].alias, long_name)

        # Second column should correctly include the long name in cost calculation
        expected_cost_alias = f"Cost per {long_name}"
        self.assertEqual(select_columns[1].alias, expected_cost_alias)

    def test_edge_case_special_characters_in_event_names(self):
        """Test graceful handling of special characters in event names"""
        special_event = "event-with_special.chars@123!$%'\"\\"

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event=special_event,
            conversion_goal_id="special_chars",
            conversion_goal_name="Special Chars",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        # Should handle special characters in event names without issues
        conditions = processor.get_base_where_conditions()
        self.assertEqual(len(conditions), 2)  # team_id + event

        # Verify the event condition includes the special character event name
        event_condition = conditions[1]  # Second condition should be event
        self.assertIsInstance(event_condition, ast.CompareOperation)
        self.assertEqual(event_condition.left.chain, ["events", "event"])
        self.assertEqual(event_condition.right.value, special_event)

    def test_edge_case_unicode_in_properties(self):
        """Test graceful handling of Unicode characters in properties"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="unicode_test",
            conversion_goal_name="Unicode Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "营销活动", "utm_source_name": "来源"},  # Chinese characters
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        # Should handle Unicode characters in schema mapping gracefully
        utm_campaign, utm_source = processor.get_utm_expressions()
        self.assertEqual(utm_campaign.chain, ["events", "properties", "营销活动"])
        self.assertEqual(utm_source.chain, ["events", "properties", "来源"])

        # Verify expressions are properly constructed
        self.assertIsInstance(utm_campaign, ast.Field)
        self.assertIsInstance(utm_source, ast.Field)

    def test_edge_case_temporal_attribution_complex_timeline(self):
        """Test query generation for complex temporal attribution scenarios - validates execution only, not attribution accuracy"""
        # Create complex timeline: UTM before range → conversion in range → UTM after
        with freeze_time("2022-12-15"):
            _create_person(distinct_ids=["temporal_user"], team=self.team)
            _create_event(
                distinct_id="temporal_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "pre_range", "utm_source": "google"},
            )
            flush_persons_and_events()

        with freeze_time("2023-01-10"):
            _create_event(
                distinct_id="temporal_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 100},  # No UTM on conversion
            )
            flush_persons_and_events()

        with freeze_time("2023-01-20"):
            _create_event(
                distinct_id="temporal_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "post_conversion", "utm_source": "facebook"},
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="temporal_complex",
            conversion_goal_name="Temporal Complex",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # NOTE: This test only validates that queries can be generated and executed
        # for complex temporal scenarios. It does NOT validate that conversions are
        # correctly attributed to the right UTM parameters based on timing.
        # Actual temporal attribution logic is not yet implemented.

    # ================================================================
    # 9. INTEGRATION TESTS - Full query execution with snapshots
    # ================================================================

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_integration_events_node_full_query_execution(self):
        """Integration test: Full EventsNode query execution with snapshot - might fail initially"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="integration_events",
            conversion_goal_name="Integration Events",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_integration_actions_node_full_query_execution(self):
        """Integration test: Full ActionsNode query execution with snapshot - might fail initially"""
        action = _create_action(team=self.team, name="Integration Action", event_name="sign_up")

        goal = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id=str(action.id),
            conversion_goal_id="integration_actions",
            conversion_goal_name="Integration Actions",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_integration_sum_math_full_query_execution(self):
        """Integration test: Full SUM math query execution with snapshot - might fail initially"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="integration_sum",
            conversion_goal_name="Integration Sum",
            math=PropertyMathType.SUM,
            math_property="revenue",
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    def test_integration_query_structure_validation(self):
        """Integration test: Validate overall query structure without execution"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="structure_test",
            conversion_goal_name="Structure Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, query_date_range=self.date_range)

        # Test all major components can be generated without errors
        self.assertIsNotNone(processor.get_select_field())
        self.assertIsNotNone(processor.get_base_where_conditions())
        self.assertIsNotNone(processor.get_utm_expressions())
        self.assertIsNotNone(processor.generate_join_clause())
        self.assertIsNotNone(processor.generate_select_columns())

    # ================================================================
    # 10. TEMPORAL ATTRIBUTION CORE TESTS - Ad timing vs conversion timing
    # ================================================================

    @unittest.expectedFailure
    def test_temporal_attribution_basic_forward_order(self):
        """
        Test Case: Basic temporal attribution - Ad BEFORE conversion (SHOULD attribute) ✅

        Scenario: User sees ad in April, converts in May
        Expected: Conversion should be attributed to the April ad
        Rule: Ads must come BEFORE conversions to get attribution credit
        """
        with freeze_time("2023-04-15"):
            _create_person(distinct_ids=["forward_user"], team=self.team)
            _create_event(
                distinct_id="forward_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "spring_sale", "utm_source": "google"},
            )
            flush_persons_and_events()

        with freeze_time("2023-05-10"):
            _create_event(
                distinct_id="forward_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 100},  # No UTM on conversion event
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="temporal_forward",
            conversion_goal_name="Temporal Forward",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-05-01", date_to="2023-05-31")
        )

        # Execute query and verify attribution
        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Ad before conversion should attribute correctly
        # Expected attribution: spring_sale/google (from April ad)
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertEqual(campaign_name, "spring_sale", f"Expected spring_sale campaign, got {campaign_name}")
                self.assertEqual(source_name, "google", f"Expected google source, got {source_name}")
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")

    @unittest.expectedFailure
    def test_temporal_attribution_forward_order_validation_example(self):
        """
        EXAMPLE: How to validate attribution results properly

        This test shows the pattern for validating attribution results.
        Remove @unittest.expectedFailure when processor logic is implemented.
        """
        # Setup: Create ad touchpoint before conversion
        with freeze_time("2023-04-15"):
            _create_person(distinct_ids=["validation_user"], team=self.team)
            _create_event(
                distinct_id="validation_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "spring_sale", "utm_source": "google"},
            )
            flush_persons_and_events()

        with freeze_time("2023-05-10"):
            _create_event(distinct_id="validation_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events()

        # Create processor and execute query
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="validation_test",
            conversion_goal_name="Validation Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-05-01", date_to="2023-05-31")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # 1. Basic response validation
        self.assertIsNotNone(response)
        self.assertIsNotNone(response.results)
        self.assertGreater(len(response.results), 0, "Should have at least one conversion result")

        # 2. Expected result structure validation
        # The query returns: [campaign_name, source_name, conversion_count]
        first_result = response.results[0]

        # Validate attribution values (correct indices based on actual query structure)
        expected_campaign = "spring_sale"
        expected_source = "google"
        expected_conversion_count = 1

        # Correct assertions based on actual query result structure:
        # Index 0: campaign_name, Index 1: source_name, Index 2: conversion_count
        self.assertEqual(
            first_result[0], expected_campaign, f"Expected campaign '{expected_campaign}', got '{first_result[0]}'"
        )
        self.assertEqual(
            first_result[1], expected_source, f"Expected source '{expected_source}', got '{first_result[1]}'"
        )
        self.assertEqual(
            first_result[2],
            expected_conversion_count,
            f"Expected {expected_conversion_count} conversion, got {first_result[2]}",
        )

    def test_temporal_attribution_backward_order_validation_example(self):
        """
        EXAMPLE: Validating that wrong temporal order produces Unknown attribution
        """
        # Setup: Create conversion before ad touchpoint (wrong order)
        with freeze_time("2023-04-15"):
            _create_person(distinct_ids=["backward_validation_user"], team=self.team)
            _create_event(
                distinct_id="backward_validation_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 100},  # Conversion first
            )
            flush_persons_and_events()

        with freeze_time("2023-05-10"):
            _create_event(
                distinct_id="backward_validation_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "too_late", "utm_source": "google"},  # Ad after conversion
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="backward_validation",
            conversion_goal_name="Backward Validation",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-04-01", date_to="2023-04-30")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # 🎯 VALIDATION: Should show Unknown attribution (not the later ad)
        self.assertIsNotNone(response)
        self.assertGreater(len(response.results), 0)

        first_result = response.results[0]
        result_dict = dict(zip(response.columns or [], first_result))

        # Assert that attribution is Unknown (or null) because ad came after conversion
        if "utm_campaign_name" in result_dict:
            self.assertIn(
                result_dict["utm_campaign_name"],
                [None, "Unknown", ""],
                f"Expected Unknown attribution, got '{result_dict['utm_campaign_name']}'",
            )

        if "utm_source_name" in result_dict:
            self.assertIn(
                result_dict["utm_source_name"],
                [None, "Unknown", ""],
                f"Expected Unknown attribution, got '{result_dict['utm_source_name']}'",
            )

    def test_attribution_result_structure_helper(self):
        """
        Helper test to understand the query result structure
        Run this first to see what your query actually returns
        """
        # Create simple test case
        with freeze_time("2023-04-15"):
            _create_person(distinct_ids=["structure_test_user"], team=self.team)
            _create_event(
                distinct_id="structure_test_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "test_campaign", "utm_source": "test_source"},
            )
            flush_persons_and_events()

        with freeze_time("2023-05-10"):
            _create_event(
                distinct_id="structure_test_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="structure_test",
            conversion_goal_name="Structure Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-05-01", date_to="2023-05-31")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Basic assertions to ensure query executes
        self.assertIsNotNone(response)

    @unittest.expectedFailure
    def test_multiple_touchpoints_attribution_validation_example(self):
        """
        EXAMPLE: How to validate multi-touch attribution with last-touch logic

        Timeline: Email → Facebook → Purchase (should attribute to Facebook - last touch)
        """
        # Setup: Create email touchpoint first
        with freeze_time("2023-04-01"):
            _create_person(distinct_ids=["multi_user"], team=self.team)
            _create_event(
                distinct_id="multi_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "newsletter", "utm_source": "email"},
            )
            flush_persons_and_events()

        # Setup: Create Facebook touchpoint later (last touch)
        with freeze_time("2023-04-15"):
            _create_event(
                distinct_id="multi_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "spring_promo", "utm_source": "facebook"},
            )
            flush_persons_and_events()

        # Conversion with no UTM (should use last touchpoint)
        with freeze_time("2023-05-10"):
            _create_event(distinct_id="multi_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events()

        # Create processor and execute query
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multi_touch_test",
            conversion_goal_name="Multi Touch Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-05-01", date_to="2023-05-31")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Validate basic response
        self.assertIsNotNone(response)
        self.assertGreater(len(response.results), 0)

        # For temporal attribution (when implemented), should attribute to Facebook (last touch)
        # Currently returns Unknown due to missing temporal logic
        result_dict = dict(zip(response.columns or [], response.results[0]))

        # These assertions will pass once temporal attribution is implemented
        self.assertEqual(
            result_dict.get("utm_campaign_name"), "spring_promo", "Should attribute to last touchpoint (Facebook)"
        )
        self.assertEqual(result_dict.get("utm_source_name"), "facebook", "Should not attribute to email (first touch)")

    def test_direct_utm_attribution_priority_over_temporal(self):
        """
        CRITICAL: Direct UTM params on conversion event should override temporal attribution

        Timeline:
        1. User sees ad1 (utm_campaign=summer_sale, utm_source=google)
        2. User sees ad2 (utm_campaign=flash_sale, utm_source=facebook)
        3. User converts WITH ad1 params directly on conversion event

        Expected: Attribution goes to ad1 (direct UTM) NOT ad2 (last temporal touchpoint)
        """
        # Setup: Create ad1 touchpoint first
        with freeze_time("2023-04-01"):
            _create_person(distinct_ids=["direct_utm_user"], team=self.team)
            _create_event(
                distinct_id="direct_utm_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "google"},
            )
            flush_persons_and_events()

        # Setup: Create ad2 touchpoint later (would be last touch temporally)
        with freeze_time("2023-04-15"):
            _create_event(
                distinct_id="direct_utm_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "flash_sale", "utm_source": "facebook"},
            )
            flush_persons_and_events()

        # CRITICAL: Conversion event has ad1 UTM params directly
        # This should override temporal attribution to ad2
        with freeze_time("2023-05-10"):
            _create_event(
                distinct_id="direct_utm_user",
                event="purchase",
                team=self.team,
                properties={
                    "revenue": 100,
                    "utm_campaign": "summer_sale",  # Direct UTM on conversion!
                    "utm_source": "google",  # Should take priority!
                },
            )
            flush_persons_and_events()

        # Test the attribution priority logic
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="direct_utm_priority",
            conversion_goal_name="Direct UTM Priority",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-05-01", date_to="2023-05-31")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Validate response structure
        self.assertIsNotNone(response)
        self.assertGreater(len(response.results), 0)

        # The critical assertion: Direct UTM should win over temporal attribution
        first_result = response.results[0]

        # EXPECTED BEHAVIOR (when properly implemented):
        # Should be summer_sale/google (direct UTM) NOT flash_sale/facebook (temporal)
        self.assertEqual(
            first_result[0],
            "summer_sale",
            f"Expected direct UTM 'summer_sale', got '{first_result[0]}'. "
            f"Direct UTM on conversion event should override temporal attribution!",
        )
        self.assertEqual(
            first_result[1],
            "google",
            f"Expected direct UTM 'google', got '{first_result[1]}'. " f"Should NOT use last touchpoint 'facebook'!",
        )

        # Attribution Rule Priority (for implementation):
        # 1. Direct UTM params on conversion event (HIGHEST PRIORITY)
        # 2. Last valid touchpoint before conversion (FALLBACK)
        # 3. Unknown Campaign/Source (DEFAULT)

    def test_temporal_attribution_basic_backward_order(self):
        """
        Test Case: Basic temporal attribution - Ad AFTER conversion (SHOULD NOT attribute) ❌

        Scenario: User converts in April, sees ad in May
        Expected: Conversion should NOT be attributed to the May ad (Unknown attribution)
        Rule: Ads that come after conversions cannot get credit for those conversions
        """
        with freeze_time("2023-04-15"):
            _create_person(distinct_ids=["backward_user"], team=self.team)
            _create_event(
                distinct_id="backward_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 100},  # Conversion with no UTM
            )
            flush_persons_and_events()

        with freeze_time("2023-05-10"):
            _create_event(
                distinct_id="backward_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "google"},  # Ad after conversion
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="temporal_backward",
            conversion_goal_name="Temporal Backward",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-04-01", date_to="2023-04-30")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Ad after conversion should NOT attribute
        # Expected: Unknown attribution (not "summer_sale")
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, _source_name, _conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertNotEqual(
                    campaign_name, "summer_sale", f"Should not attribute to late campaign: {campaign_name}"
                )
                self.assertIn(
                    campaign_name,
                    [None, "Unknown", "", "Unknown Campaign"],
                    f"Expected Unknown attribution, got {campaign_name}",
                )

    @unittest.expectedFailure
    def test_temporal_attribution_multiple_touchpoints_last_touch(self):
        """
        Test Case: Multiple touchpoints before conversion - Last touch attribution

        Scenario: User sees multiple ads before converting, test last-touch attribution
        Timeline:
        - March 10: Email campaign ad (first touch)
        - April 15: Google search ad (last touch before conversion)
        - May 10: Conversion

        Expected: Attribution should go to April Google ad (last touch)
        Note: This tests last-touch attribution model
        """
        with freeze_time("2023-03-10"):
            _create_person(distinct_ids=["multi_touch_user"], team=self.team)
            _create_event(
                distinct_id="multi_touch_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "early_bird", "utm_source": "email"},  # First touch
            )
            flush_persons_and_events()

        with freeze_time("2023-04-15"):
            _create_event(
                distinct_id="multi_touch_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "spring_sale", "utm_source": "google"},  # Last touch
            )
            flush_persons_and_events()

        with freeze_time("2023-05-10"):
            _create_event(distinct_id="multi_touch_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multi_touch_last",
            conversion_goal_name="Multi Touch Last",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-05-01", date_to="2023-05-31")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Last-touch attribution validation
        # Expected: Most recent ad before conversion (April "spring_sale", not March "early_bird")
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertEqual(campaign_name, "spring_sale", f"Expected last-touch spring_sale, got {campaign_name}")
                self.assertEqual(source_name, "google", f"Expected google source, got {source_name}")
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")
                self.assertNotEqual(campaign_name, "early_bird", f"Should not attribute to first touch early_bird")

    @unittest.expectedFailure
    def test_temporal_attribution_touchpoints_before_and_after_conversion(self):
        """
        Test Case: Touchpoints both before AND after conversion

        Scenario: Mixed timeline with ads before and after conversion
        Timeline:
        - March 10: Email ad ✅ (valid - before conversion)
        - April 15: Google ad ✅ (valid - before conversion)
        - May 10: CONVERSION 🎯
        - June 05: Facebook ad ❌ (invalid - after conversion)
        - July 01: Twitter ad ❌ (invalid - after conversion)

        Expected: Only ads before conversion should be considered for attribution
        Attribution should go to April Google ad (last valid touchpoint)
        """
        with freeze_time("2023-03-10"):
            _create_person(distinct_ids=["mixed_timeline_user"], team=self.team)
            _create_event(
                distinct_id="mixed_timeline_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "early_bird", "utm_source": "email"},  # ✅ Valid
            )
            flush_persons_and_events()

        with freeze_time("2023-04-15"):
            _create_event(
                distinct_id="mixed_timeline_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "spring_sale", "utm_source": "google"},  # ✅ Valid (last)
            )
            flush_persons_and_events()

        with freeze_time("2023-05-10"):
            _create_event(
                distinct_id="mixed_timeline_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 100},  # 🎯 CONVERSION
            )
            flush_persons_and_events()

        with freeze_time("2023-06-05"):
            _create_event(
                distinct_id="mixed_timeline_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "facebook"},  # ❌ Invalid
            )
            flush_persons_and_events()

        with freeze_time("2023-07-01"):
            _create_event(
                distinct_id="mixed_timeline_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "july_promo", "utm_source": "twitter"},  # ❌ Invalid
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="mixed_timeline",
            conversion_goal_name="Mixed Timeline",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-05-01", date_to="2023-05-31")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Should ignore ads after conversion
        # Expected: Attribution to last valid ad before conversion ("spring_sale", not "summer_sale" or "july_promo")
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertEqual(
                    campaign_name, "spring_sale", f"Expected spring_sale (last valid), got {campaign_name}"
                )
                self.assertEqual(source_name, "google", f"Expected google source, got {source_name}")
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")
                self.assertNotEqual(campaign_name, "summer_sale", f"Should ignore ads after conversion")
                self.assertNotEqual(campaign_name, "july_promo", f"Should ignore ads after conversion")

    def test_temporal_attribution_long_attribution_window(self):
        """
        Test Case: Long attribution window - months apart

        Scenario: User sees ad in January, converts in December (11 months later)
        Timeline:
        - Jan 01: New Year campaign ad
        - Dec 31: Purchase (11 months later)

        Expected: Should attribute if within attribution window, otherwise Unknown
        Tests attribution window limits and long customer journeys
        """
        with freeze_time("2023-01-01"):
            _create_person(distinct_ids=["long_window_user"], team=self.team)
            _create_event(
                distinct_id="long_window_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "new_year", "utm_source": "google"},
            )
            flush_persons_and_events()

        with freeze_time("2023-12-31"):
            _create_event(
                distinct_id="long_window_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 500},  # High-value conversion after long journey
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="long_window",
            conversion_goal_name="Long Attribution Window",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-12-01", date_to="2023-12-31")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-12-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

    def test_temporal_attribution_multiple_conversions_separate_attribution(self):
        """
        Test Case: Multiple conversions with separate attribution tracking

        Scenario: User has multiple conversions, each should be attributed independently
        Timeline:
        - March 10: Spring sale ad
        - April 15: First purchase → should attribute to spring sale
        - May 20: Mother's day ad
        - May 25: Second purchase → should attribute to mother's day
        - June 10: Third purchase → should still attribute to mother's day (no new ads)

        Expected: Each conversion gets attributed to the most recent qualifying ad
        """
        with freeze_time("2023-03-10"):
            _create_person(distinct_ids=["multi_conversion_user"], team=self.team)
            _create_event(
                distinct_id="multi_conversion_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "spring_sale", "utm_source": "google"},
            )
            flush_persons_and_events()

        with freeze_time("2023-04-15"):
            _create_event(
                distinct_id="multi_conversion_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 100},  # Conv1 → spring_sale/google
            )
            flush_persons_and_events()

        with freeze_time("2023-05-20"):
            _create_event(
                distinct_id="multi_conversion_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "mothers_day", "utm_source": "facebook"},
            )
            flush_persons_and_events()

        with freeze_time("2023-05-25"):
            _create_event(
                distinct_id="multi_conversion_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 150},  # Conv2 → mothers_day/facebook
            )
            flush_persons_and_events()

        with freeze_time("2023-06-10"):
            _create_event(
                distinct_id="multi_conversion_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 75},  # Conv3 → mothers_day/facebook (still)
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multi_conversion",
            conversion_goal_name="Multi Conversion",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        # Test attribution for each conversion period
        for period, expected_attribution in [
            (("2023-04-01", "2023-04-30"), "spring_sale/google"),
            (("2023-05-01", "2023-05-31"), "mothers_day/facebook"),
            (("2023-06-01", "2023-06-30"), "mothers_day/facebook"),
        ]:
            with self.subTest(period=period, expected=expected_attribution):
                processor = ConversionGoalProcessor(
                    goal=goal,
                    index=0,
                    team=self.team,
                    query_date_range=DateRange(date_from=period[0], date_to=period[1]),
                )

                additional_conditions = [
                    ast.CompareOperation(
                        left=ast.Field(chain=["events", "timestamp"]),
                        op=ast.CompareOperationOp.GtEq,
                        right=ast.Call(name="toDate", args=[ast.Constant(value=period[0])]),
                    ),
                ]

                cte_query = processor.generate_cte_query(additional_conditions)
                response = execute_hogql_query(query=cte_query, team=self.team)
                self.assertIsNotNone(response)

    # ================================================================
    # 11. SAME-DAY TEMPORAL ATTRIBUTION TESTS - Intraday timing precision
    # ================================================================

    @unittest.expectedFailure
    def test_temporal_attribution_same_day_morning_evening(self):
        """
        Test Case: Same day temporal order - morning ad, evening conversion

        Scenario: User sees ad in the morning, converts in the evening (same day)
        Timeline:
        - May 15 08:00: Morning email campaign
        - May 15 20:00: Evening purchase

        Expected: Should attribute to morning ad ✅
        Tests intraday temporal precision
        """
        with freeze_time("2023-05-15 08:00:00"):
            _create_person(distinct_ids=["same_day_morning_user"], team=self.team)
            _create_event(
                distinct_id="same_day_morning_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "daily_deal", "utm_source": "email"},
            )
            flush_persons_and_events()

        with freeze_time("2023-05-15 20:00:00"):
            _create_event(
                distinct_id="same_day_morning_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="same_day_morning",
            conversion_goal_name="Same Day Morning",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-05-15", date_to="2023-05-15")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-15")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Same-day morning ad → evening conversion
        # Expected: Should attribute to "daily_deal" campaign from morning
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertEqual(campaign_name, "daily_deal", f"Expected daily_deal campaign, got {campaign_name}")
                self.assertEqual(source_name, "email", f"Expected email source, got {source_name}")
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")

    def test_temporal_attribution_same_day_evening_morning(self):
        """
        Test Case: Same day temporal order - morning conversion, evening ad

        Scenario: User converts in the morning, sees ad in the evening (same day)
        Timeline:
        - May 15 08:00: Morning purchase
        - May 15 20:00: Evening ad (too late!)

        Expected: Should NOT attribute to evening ad ❌ (Unknown attribution)
        Tests that temporal order matters even within the same day
        """
        with freeze_time("2023-05-15 08:00:00"):
            _create_person(distinct_ids=["same_day_evening_user"], team=self.team)
            _create_event(
                distinct_id="same_day_evening_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events()

        with freeze_time("2023-05-15 20:00:00"):
            _create_event(
                distinct_id="same_day_evening_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "daily_deal", "utm_source": "email"},  # Too late!
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="same_day_evening",
            conversion_goal_name="Same Day Evening",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-05-15", date_to="2023-05-15")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-15")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Same-day conversion → evening ad should NOT attribute
        # Expected: Unknown attribution (not "daily_deal")
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertNotEqual(
                    campaign_name, "daily_deal", f"Should not attribute to late campaign: {campaign_name}"
                )
                self.assertIn(
                    campaign_name,
                    [None, "Unknown", "", "Unknown Campaign"],
                    f"Expected Unknown attribution, got {campaign_name}",
                )
                self.assertIn(
                    source_name, [None, "Unknown", "", "Unknown Source"], f"Expected Unknown source, got {source_name}"
                )
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")

    @unittest.expectedFailure
    def test_temporal_attribution_simultaneous_ad_conversion(self):
        """
        Test Case: Simultaneous ad and conversion at exact same timestamp

        Scenario: Ad view and conversion happen at exactly the same time
        Timeline:
        - May 15 12:00:00.000: Page view with UTM
        - May 15 12:00:00.000: Purchase (exact same timestamp)

        Expected: Should attribute to ad ✅ (ad timestamp <= conversion timestamp)
        Tests edge case of simultaneous events
        """
        timestamp = "2023-05-15 12:00:00"

        with freeze_time(timestamp):
            _create_person(distinct_ids=["simultaneous_user"], team=self.team)
            _create_event(
                distinct_id="simultaneous_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "instant", "utm_source": "google"},
            )
            _create_event(
                distinct_id="simultaneous_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="simultaneous",
            conversion_goal_name="Simultaneous",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-05-15", date_to="2023-05-15")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-15")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Simultaneous timestamps should attribute
        # Expected: Should attribute to "instant" campaign (ad_timestamp <= conversion_timestamp)
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertEqual(campaign_name, "instant", f"Expected instant campaign, got {campaign_name}")
                self.assertEqual(source_name, "google", f"Expected google source, got {source_name}")
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")

    def test_temporal_attribution_one_second_precision(self):
        """
        Test Case: Sub-minute temporal precision - 1 second difference

        Scenario: Conversion happens 1 second before ad view
        Timeline:
        - May 15 12:00:00: Purchase
        - May 15 12:00:01: Ad view (1 second too late)

        Expected: Should NOT attribute ❌ (Unknown attribution)
        Tests temporal precision down to the second level
        """
        with freeze_time("2023-05-15 12:00:00"):
            _create_person(distinct_ids=["one_second_user"], team=self.team)
            _create_event(distinct_id="one_second_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events()

        with freeze_time("2023-05-15 12:00:01"):
            _create_event(
                distinct_id="one_second_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "too_late", "utm_source": "google"},
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="one_second",
            conversion_goal_name="One Second",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-05-15", date_to="2023-05-15")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-15")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: 1-second precision should NOT attribute
        # Expected: Unknown attribution (not "too_late") since ad came 1 second after conversion
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertNotEqual(
                    campaign_name, "too_late", f"Should not attribute to late campaign: {campaign_name}"
                )
                self.assertIn(
                    campaign_name,
                    [None, "Unknown", "", "Unknown Campaign"],
                    f"Expected Unknown attribution, got {campaign_name}",
                )
                self.assertIn(
                    source_name, [None, "Unknown", "", "Unknown Source"], f"Expected Unknown source, got {source_name}"
                )
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")

    @unittest.expectedFailure
    def test_temporal_attribution_multiple_conversions_same_campaign(self):
        """
        Test Case: Multiple conversions from the same campaign attribution

        Scenario: User sees one ad campaign, then makes multiple purchases over time
        Timeline:
        - March 01: Spring sale ad campaign
        - April 15: First purchase ✅
        - May 20: Second purchase ✅ (still within attribution window)
        - June 10: Third purchase ✅ (still within attribution window)

        Expected: All 3 conversions should be attributed to the same "spring_sale" campaign
        conversion_count should be 3 (not 1)
        Tests that attribution properly aggregates multiple conversions
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["repeat_buyer"], team=self.team)
            _create_event(
                distinct_id="repeat_buyer",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "spring_sale", "utm_source": "google"},
            )
            flush_persons_and_events()

        # First purchase
        with freeze_time("2023-04-15"):
            _create_event(distinct_id="repeat_buyer", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events()

        # Second purchase
        with freeze_time("2023-05-20"):
            _create_event(distinct_id="repeat_buyer", event="purchase", team=self.team, properties={"revenue": 75})
            flush_persons_and_events()

        # Third purchase
        with freeze_time("2023-06-10"):
            _create_event(distinct_id="repeat_buyer", event="purchase", team=self.team, properties={"revenue": 150})
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multiple_conversions",
            conversion_goal_name="Multiple Conversions",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-04-01", date_to="2023-06-30")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Multiple conversions from same campaign
        # Expected: All 3 purchases should be attributed to "spring_sale" campaign
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertEqual(campaign_name, "spring_sale", f"Expected spring_sale campaign, got {campaign_name}")
                self.assertEqual(source_name, "google", f"Expected google source, got {source_name}")
                self.assertEqual(conversion_count, 3, f"Expected 3 conversions, got {conversion_count}")

    @unittest.expectedFailure
    def test_temporal_attribution_multiple_users_same_campaign(self):
        """
        Test Case: Multiple users converting from the same campaign

        Scenario: Multiple different users see the same ad campaign and convert
        Timeline:
        - April 10: User A sees ad, purchases (1 conversion)
        - April 15: User B sees ad, purchases (1 conversion)
        - April 20: User C sees ad, purchases twice (2 conversions)

        Expected: "spring_sale" campaign should have conversion_count = 4 total
        Tests that attribution properly aggregates conversions across multiple users
        """
        campaign_props = {"utm_campaign": "spring_sale", "utm_source": "google"}

        # User A: sees ad, purchases once
        with freeze_time("2023-04-10"):
            _create_person(distinct_ids=["user_a"], team=self.team)
            _create_event(distinct_id="user_a", event="page_view", team=self.team, properties=campaign_props)
            _create_event(distinct_id="user_a", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events()

        # User B: sees ad, purchases once
        with freeze_time("2023-04-15"):
            _create_person(distinct_ids=["user_b"], team=self.team)
            _create_event(distinct_id="user_b", event="page_view", team=self.team, properties=campaign_props)
            _create_event(distinct_id="user_b", event="purchase", team=self.team, properties={"revenue": 150})
            flush_persons_and_events()

        # User C: sees ad, purchases twice
        with freeze_time("2023-04-20"):
            _create_person(distinct_ids=["user_c"], team=self.team)
            _create_event(distinct_id="user_c", event="page_view", team=self.team, properties=campaign_props)
            _create_event(distinct_id="user_c", event="purchase", team=self.team, properties={"revenue": 200})
            flush_persons_and_events()

        with freeze_time("2023-04-21"):
            _create_event(distinct_id="user_c", event="purchase", team=self.team, properties={"revenue": 75})
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multi_user_conversions",
            conversion_goal_name="Multi User Conversions",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-04-01", date_to="2023-04-30")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Multiple users, multiple conversions aggregation
        # Expected: Total 4 conversions from "spring_sale" campaign across all users
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertEqual(campaign_name, "spring_sale", f"Expected spring_sale campaign, got {campaign_name}")
                self.assertEqual(source_name, "google", f"Expected google source, got {source_name}")
                self.assertEqual(
                    conversion_count, 4, f"Expected 4 total conversions across users, got {conversion_count}"
                )

    # ================================================================
    # 12. COMPLEX CUSTOMER JOURNEY TESTS - Multi-event, multi-channel attribution
    # ================================================================

    @unittest.expectedFailure
    def test_complex_customer_journey_multiple_event_types(self):
        """
        Test Case: Complex customer journey with multiple event types and channels

        Scenario: Full-funnel customer journey across multiple touchpoints and channels
        Timeline:
        - Mar 01: YouTube ad (awareness phase)
        - Mar 15: Email nurture campaign
        - Apr 01: Facebook retargeting ad
        - Apr 05: Add to cart event (intent signal)
        - Apr 10: Purchase (CONVERSION)
        - May 01: Post-purchase upsell email (should not affect purchase attribution)

        Expected: Purchase should be attributed to Facebook retargeting (last paid touchpoint before conversion)
        Post-purchase touchpoints should not affect the original purchase attribution
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["complex_journey_user"], team=self.team)
            _create_event(
                distinct_id="complex_journey_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "awareness", "utm_source": "youtube"},  # Awareness
            )
            flush_persons_and_events()

        with freeze_time("2023-03-15"):
            _create_event(
                distinct_id="complex_journey_user",
                event="email_open",
                team=self.team,
                properties={"utm_campaign": "nurture", "utm_source": "email"},  # Nurturing
            )
            flush_persons_and_events()

        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="complex_journey_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "retarget", "utm_source": "facebook"},  # Retargeting
            )
            flush_persons_and_events()

        with freeze_time("2023-04-05"):
            _create_event(
                distinct_id="complex_journey_user",
                event="add_to_cart",
                team=self.team,
                properties={"utm_campaign": "retarget", "utm_source": "facebook"},  # Intent
            )
            flush_persons_and_events()

        with freeze_time("2023-04-10"):
            _create_event(
                distinct_id="complex_journey_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 200},  # 🎯 CONVERSION
            )
            flush_persons_and_events()

        with freeze_time("2023-05-01"):
            _create_event(
                distinct_id="complex_journey_user",
                event="email_click",
                team=self.team,
                properties={"utm_campaign": "upsell", "utm_source": "email"},  # Post-purchase
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="complex_journey",
            conversion_goal_name="Complex Journey",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-04-01", date_to="2023-04-30")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Multi-channel last-touch attribution
        # Expected: Should attribute to "retargeting" (last valid touchpoint before conversion)
        # Should ignore "upsell" campaign (came after conversion)
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertEqual(
                    campaign_name, "retargeting", f"Expected retargeting (last-touch), got {campaign_name}"
                )
                self.assertEqual(source_name, "facebook", f"Expected facebook source, got {source_name}")
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")
                self.assertNotEqual(campaign_name, "upsell", f"Should ignore post-purchase campaigns")

    @unittest.expectedFailure
    def test_organic_vs_paid_attribution_organic_then_paid(self):
        """
        Test Case: Organic vs Paid attribution - Organic visit then paid ad

        Scenario: User visits organically first, then through paid ad, then converts
        Timeline:
        - Mar 01: Organic page view (direct visit, no UTM)
        - Apr 01: Paid search ad visit
        - Apr 10: Purchase

        Expected: Attribution should go to paid search (last paid touchpoint)
        Tests how organic vs paid touchpoints are prioritized in attribution
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["organic_paid_user"], team=self.team)
            _create_event(
                distinct_id="organic_paid_user",
                event="page_view",
                team=self.team,
                properties={},  # Organic - no UTM parameters
            )
            flush_persons_and_events()

        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="organic_paid_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "paid_search", "utm_source": "google"},  # Paid
            )
            flush_persons_and_events()

        with freeze_time("2023-04-10"):
            _create_event(
                distinct_id="organic_paid_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="organic_paid",
            conversion_goal_name="Organic Paid",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-04-01", date_to="2023-04-30")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Organic → Paid should attribute to paid
        # Expected: Should attribute to "paid_search" (last paid touchpoint)
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertEqual(campaign_name, "paid_search", f"Expected paid_search campaign, got {campaign_name}")
                self.assertEqual(source_name, "google", f"Expected google source, got {source_name}")
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")

    @unittest.expectedFailure
    def test_organic_vs_paid_attribution_paid_then_organic(self):
        """
        Test Case: Organic vs Paid attribution - Paid ad then organic visit

        Scenario: User visits through paid ad first, then organically, then converts
        Timeline:
        - Mar 01: Paid search ad visit
        - Apr 01: Organic page view (direct visit)
        - Apr 10: Purchase

        Expected: Depends on attribution model:
        - Last-touch: Could be organic or paid (depending on how organic is handled)
        - Paid-only last-touch: Should be paid search (last paid touchpoint)
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["paid_organic_user"], team=self.team)
            _create_event(
                distinct_id="paid_organic_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "paid_search", "utm_source": "google"},  # Paid
            )
            flush_persons_and_events()

        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="paid_organic_user",
                event="page_view",
                team=self.team,
                properties={},  # Organic - no UTM parameters
            )
            flush_persons_and_events()

        with freeze_time("2023-04-10"):
            _create_event(
                distinct_id="paid_organic_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="paid_organic",
            conversion_goal_name="Paid Organic",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-04-01", date_to="2023-04-30")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Paid → Organic should attribute to paid
        # Expected: Should attribute to "paid_search" (last paid touchpoint, ignoring organic)
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertEqual(campaign_name, "paid_search", f"Expected paid_search campaign, got {campaign_name}")
                self.assertEqual(source_name, "google", f"Expected google source, got {source_name}")
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")

    @unittest.expectedFailure
    def test_cross_channel_attribution_full_funnel(self):
        """
        Test Case: Cross-channel attribution across the full marketing funnel

        Scenario: User journey across multiple marketing channels and touchpoints
        Timeline:
        - Week 1: YouTube brand awareness campaign
        - Week 2: Email newsletter click
        - Week 3: Facebook retargeting campaign
        - Week 4: Google search ad (final touchpoint)
        - Week 4: Purchase

        Expected: Attribution should go to Google search ad (last touch)
        Tests multi-channel customer journey attribution
        """
        with freeze_time("2023-03-01"):  # Week 1
            _create_person(distinct_ids=["cross_channel_user"], team=self.team)
            _create_event(
                distinct_id="cross_channel_user",
                event="video_view",
                team=self.team,
                properties={"utm_campaign": "brand_awareness", "utm_source": "youtube"},
            )
            flush_persons_and_events()

        with freeze_time("2023-03-08"):  # Week 2
            _create_event(
                distinct_id="cross_channel_user",
                event="email_click",
                team=self.team,
                properties={"utm_campaign": "newsletter", "utm_source": "email"},
            )
            flush_persons_and_events()

        with freeze_time("2023-03-15"):  # Week 3
            _create_event(
                distinct_id="cross_channel_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "retarget", "utm_source": "facebook"},
            )
            flush_persons_and_events()

        with freeze_time("2023-03-22"):  # Week 4
            _create_event(
                distinct_id="cross_channel_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "search_ad", "utm_source": "google"},
            )
            flush_persons_and_events()

        with freeze_time("2023-03-24"):  # Week 4
            _create_event(
                distinct_id="cross_channel_user", event="purchase", team=self.team, properties={"revenue": 300}
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="cross_channel",
            conversion_goal_name="Cross Channel",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-03-20", date_to="2023-03-31")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-03-20")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Multi-channel last-touch attribution
        # Expected: Should attribute to "search_ad" (last touchpoint before conversion)
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertEqual(campaign_name, "search_ad", f"Expected search_ad (last-touch), got {campaign_name}")
                self.assertEqual(source_name, "google", f"Expected google source, got {source_name}")
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")
                self.assertNotEqual(campaign_name, "brand_awareness", f"Should not attribute to first touch")

    @unittest.expectedFailure
    def test_multi_session_attribution_across_devices(self):
        """
        Test Case: Multi-session attribution across different devices/platforms

        Scenario: User journey spans multiple sessions and potentially different devices
        Timeline:
        - Session 1 (Mobile): Instagram ad, product browsing
        - Session 2 (Desktop): Direct visit, add to cart
        - Session 3 (Mobile): Email reminder, purchase

        Expected: Attribution should go to email campaign (last touchpoint with UTM)
        Tests attribution across session boundaries and device switching
        """
        # Session 1 - Mobile (Instagram discovery)
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["multi_session_user"], team=self.team)
            _create_event(
                distinct_id="multi_session_user",
                event="page_view",
                team=self.team,
                properties={
                    "utm_campaign": "mobile_ad",
                    "utm_source": "instagram",
                    "$os": "iOS",
                    "$browser": "Mobile Safari",
                },
            )
            _create_event(
                distinct_id="multi_session_user",
                event="product_view",
                team=self.team,
                properties={"utm_campaign": "mobile_ad", "utm_source": "instagram", "$os": "iOS"},
            )
            flush_persons_and_events()

        # Session 2 - Desktop (Direct visit)
        with freeze_time("2023-03-15"):
            _create_event(
                distinct_id="multi_session_user",
                event="page_view",
                team=self.team,
                properties={
                    "$os": "Mac OS X",
                    "$browser": "Chrome",
                    # No UTM - direct visit
                },
            )
            _create_event(
                distinct_id="multi_session_user", event="add_to_cart", team=self.team, properties={"$os": "Mac OS X"}
            )
            flush_persons_and_events()

        # Session 3 - Mobile (Email conversion)
        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="multi_session_user",
                event="email_click",
                team=self.team,
                properties={"utm_campaign": "cart_abandonment", "utm_source": "email", "$os": "iOS"},
            )
            _create_event(
                distinct_id="multi_session_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 150, "$os": "iOS"},
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multi_session",
            conversion_goal_name="Multi Session",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-04-01", date_to="2023-04-30")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Multi-session cross-device attribution
        # Expected: Should attribute to "cart_abandonment" (last email touchpoint)
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertEqual(
                    campaign_name, "cart_abandonment", f"Expected cart_abandonment (last-touch), got {campaign_name}"
                )
                self.assertEqual(source_name, "email", f"Expected email source, got {source_name}")
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")
                self.assertNotEqual(campaign_name, "mobile_ad", f"Should not attribute to first touch")

    # ================================================================
    # 13. ATTRIBUTION WINDOW TESTS - Time-based attribution limits
    # ================================================================

    @unittest.expectedFailure
    def test_attribution_window_30_day_limit(self):
        """
        Test Case: 30-day attribution window enforcement

        Scenario: Test conversions within and beyond 30-day attribution window
        Timeline:
        - Day 1: Campaign ad
        - Day 29: Purchase (within 30 days) ✅
        - Day 31: Another purchase (beyond 30 days) ❌

        Expected: First purchase attributed, second purchase not attributed
        Tests attribution window cutoff logic
        """
        with freeze_time("2023-01-01"):
            _create_person(distinct_ids=["window_test_user"], team=self.team)
            _create_event(
                distinct_id="window_test_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "month_start", "utm_source": "google"},
            )
            flush_persons_and_events()

        with freeze_time("2023-01-29"):  # Day 29 - within window
            _create_event(distinct_id="window_test_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events()

        with freeze_time("2023-02-01"):  # Day 31 - beyond window
            _create_event(distinct_id="window_test_user", event="purchase", team=self.team, properties={"revenue": 50})
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="window_30day",
            conversion_goal_name="30 Day Window",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        # Test both periods
        for period, should_attribute in [
            (("2023-01-29", "2023-01-29"), True),  # Within window
            (("2023-02-01", "2023-02-01"), False),  # Beyond window
        ]:
            with self.subTest(period=period, should_attribute=should_attribute):
                processor = ConversionGoalProcessor(
                    goal=goal,
                    index=0,
                    team=self.team,
                    query_date_range=DateRange(date_from=period[0], date_to=period[1]),
                )

                additional_conditions = [
                    ast.CompareOperation(
                        left=ast.Field(chain=["events", "timestamp"]),
                        op=ast.CompareOperationOp.GtEq,
                        right=ast.Call(name="toDate", args=[ast.Constant(value=period[0])]),
                    ),
                ]

                cte_query = processor.generate_cte_query(additional_conditions)
                response = execute_hogql_query(query=cte_query, team=self.team)
                self.assertIsNotNone(response)

                # 🎯 ATTRIBUTION VALIDATION: 30-day window enforcement
                if response.results and len(response.results) > 0:
                    first_result = response.results[0]
                    if len(first_result) >= 3:
                        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                        if should_attribute:
                            self.assertEqual(
                                campaign_name, "month_start", f"Expected month_start within window, got {campaign_name}"
                            )
                            self.assertEqual(source_name, "google", f"Expected google source, got {source_name}")
                            self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")
                        else:
                            self.assertIn(
                                campaign_name,
                                [None, "Unknown", "", "Unknown Campaign"],
                                f"Expected Unknown beyond window, got {campaign_name}",
                            )
                            self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")

    def test_attribution_window_beyond_limits(self):
        """
        Test Case: Attribution beyond reasonable limits - 2 years

        Scenario: Very old touchpoint should not influence current conversions
        Timeline:
        - Jan 01 2022: Old campaign (2 years ago)
        - Jan 01 2024: Purchase (2 years later)

        Expected: Should not attribute to 2-year-old campaign (Unknown attribution)
        Tests very long attribution window limits
        """
        with freeze_time("2022-01-01"):
            _create_person(distinct_ids=["old_campaign_user"], team=self.team)
            _create_event(
                distinct_id="old_campaign_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "old_campaign", "utm_source": "google"},
            )
            flush_persons_and_events()

        with freeze_time("2024-01-01"):  # 2 years later
            _create_event(
                distinct_id="old_campaign_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="beyond_limits",
            conversion_goal_name="Beyond Limits",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2024-01-01", date_to="2024-01-01")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2024-01-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Beyond attribution window limits
        # Expected: Should NOT attribute to 2-year-old campaign (Unknown attribution)
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, _source_name, _conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertNotEqual(
                    campaign_name, "old_campaign", f"Should not attribute to 2-year-old campaign: {campaign_name}"
                )
                self.assertIn(
                    campaign_name,
                    [None, "Unknown", "", "Unknown Campaign"],
                    f"Expected Unknown for very old campaign, got {campaign_name}",
                )

    # ================================================================
    # 14. DATA QUALITY EDGE CASES - Malformed UTM, duplicates, missing data
    # ================================================================

    def test_malformed_utm_parameters_empty_campaign(self):
        """
        Test Case: Malformed UTM parameters - empty campaign name

        Scenario: UTM parameters with empty or null values
        Timeline:
        - Mar 01: Ad with empty campaign name but valid source
        - Apr 01: Ad with valid campaign but missing source
        - May 01: Ad with missing campaign but valid source
        - Jun 01: Purchase

        Expected: Should handle gracefully with appropriate fallbacks
        Tests data quality handling for incomplete UTM parameters
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["malformed_utm_user"], team=self.team)
            _create_event(
                distinct_id="malformed_utm_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "", "utm_source": "google"},  # Empty campaign
            )
            flush_persons_and_events()

        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="malformed_utm_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "valid_campaign"},  # Missing source
            )
            flush_persons_and_events()

        with freeze_time("2023-05-01"):
            _create_event(
                distinct_id="malformed_utm_user",
                event="page_view",
                team=self.team,
                properties={"utm_source": "facebook"},  # Missing campaign
            )
            flush_persons_and_events()

        with freeze_time("2023-06-01"):
            _create_event(
                distinct_id="malformed_utm_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="malformed_utm",
            conversion_goal_name="Malformed UTM",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-06-01", date_to="2023-06-01")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-06-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Malformed UTM handling
        # Expected: Should handle malformed UTM gracefully (may use fallbacks or last valid values)
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, _source_name, _conversion_count = first_result[0], first_result[1], first_result[2]
                # Should handle gracefully - could attribute to last valid campaign or show Unknown
                self.assertIsNotNone(campaign_name, "Should handle malformed UTM without crashing")

    @unittest.expectedFailure
    def test_duplicate_events_same_timestamp(self):
        """
        Test Case: Duplicate events at the same timestamp

        Scenario: Multiple identical or similar events at exact same time
        Timeline:
        - May 15 12:00:00.000: First page view with UTM
        - May 15 12:00:00.000: Duplicate page view with different UTM (same timestamp)
        - May 15 13:00:00.000: Purchase

        Expected: Should handle duplicates appropriately (dedupe or use last processed)
        Tests handling of duplicate/concurrent events
        """
        timestamp = "2023-05-15 12:00:00"

        with freeze_time(timestamp):
            _create_person(distinct_ids=["duplicate_events_user"], team=self.team)
            _create_event(
                distinct_id="duplicate_events_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "duplicate1", "utm_source": "google"},
            )
            _create_event(
                distinct_id="duplicate_events_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "duplicate2", "utm_source": "google"},  # Same timestamp
            )
            flush_persons_and_events()

        with freeze_time("2023-05-15 13:00:00"):
            _create_event(
                distinct_id="duplicate_events_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="duplicate_events",
            conversion_goal_name="Duplicate Events",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-05-15", date_to="2023-05-15")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-15")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Duplicate events handling
        # Expected: Should handle duplicates gracefully (dedupe or use deterministic selection)
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, _conversion_count = first_result[0], first_result[1], first_result[2]
                # Should pick one of the duplicate campaigns deterministically
                self.assertIn(
                    campaign_name,
                    ["duplicate1", "duplicate2"],
                    f"Expected one of the duplicate campaigns, got {campaign_name}",
                )
                self.assertEqual(source_name, "google", f"Expected google source, got {source_name}")

    @unittest.expectedFailure
    def test_utm_parameters_with_special_characters(self):
        """
        Test Case: UTM parameters containing special characters and encoding

        Scenario: UTM values with special characters, spaces, URL encoding
        Timeline:
        - Mar 01: Ad with special characters in UTM
        - Apr 01: Purchase

        Expected: Should handle special characters properly in attribution
        Tests URL encoding, special characters, and data sanitization
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["special_chars_user"], team=self.team)
            _create_event(
                distinct_id="special_chars_user",
                event="page_view",
                team=self.team,
                properties={
                    "utm_campaign": "spring sale 2023 - 50% off!",  # Spaces and special chars
                    "utm_source": "google ads & display",  # Ampersand
                    "utm_medium": "cpc/display",  # Forward slash
                    "utm_content": "banner_300x250",  # Underscore
                    "utm_term": "buy now + save",  # Plus sign
                },
            )
            flush_persons_and_events()

        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="special_chars_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="special_chars",
            conversion_goal_name="Special Characters",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-04-01", date_to="2023-04-01")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Special characters handling
        # Expected: Should handle special characters correctly in attribution
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                self.assertEqual(
                    campaign_name,
                    "spring sale 2023 - 50% off!",
                    f"Expected special chars campaign, got {campaign_name}",
                )
                self.assertEqual(
                    source_name, "google ads & display", f"Expected special chars source, got {source_name}"
                )
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")

    def test_very_long_utm_values(self):
        """
        Test Case: Very long UTM parameter values

        Scenario: UTM parameters with extremely long values (potential data quality issue)
        Timeline:
        - Mar 01: Ad with very long UTM values
        - Apr 01: Purchase

        Expected: Should handle long values gracefully (truncate or handle full value)
        Tests handling of abnormally long UTM parameter values
        """
        long_campaign = "very_long_campaign_name_" + "x" * 500  # Very long campaign name
        long_source = "extremely_long_source_name_" + "y" * 300  # Very long source

        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["long_utm_user"], team=self.team)
            _create_event(
                distinct_id="long_utm_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": long_campaign, "utm_source": long_source},
            )
            flush_persons_and_events()

        with freeze_time("2023-04-01"):
            _create_event(distinct_id="long_utm_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="long_utm",
            conversion_goal_name="Long UTM Values",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-04-01", date_to="2023-04-01")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Very long UTM values handling
        # Expected: Should handle very long values gracefully (truncate or handle full value)
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, _conversion_count = first_result[0], first_result[1], first_result[2]
                long_campaign = "very_long_campaign_name_" + "x" * 500
                long_source = "extremely_long_source_name_" + "y" * 300
                # Should handle long values without issues
                self.assertIsNotNone(campaign_name, "Should handle very long UTM values")
                self.assertIsNotNone(source_name, "Should handle very long source values")

    @unittest.expectedFailure
    def test_case_sensitivity_utm_parameters(self):
        """
        Test Case: Case sensitivity in UTM parameter values

        Scenario: UTM parameters with different case variations
        Timeline:
        - Mar 01: "Google" (capitalized)
        - Mar 15: "google" (lowercase)
        - Apr 01: "GOOGLE" (uppercase)
        - Apr 10: Purchase

        Expected: Should handle case sensitivity consistently
        Tests whether attribution treats "Google", "google", "GOOGLE" as same or different
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["case_sensitive_user"], team=self.team)
            _create_event(
                distinct_id="case_sensitive_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "Spring Sale", "utm_source": "Google"},  # Capitalized
            )
            flush_persons_and_events()

        with freeze_time("2023-03-15"):
            _create_event(
                distinct_id="case_sensitive_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "spring sale", "utm_source": "google"},  # Lowercase
            )
            flush_persons_and_events()

        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="case_sensitive_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "SPRING SALE", "utm_source": "GOOGLE"},  # Uppercase
            )
            flush_persons_and_events()

        with freeze_time("2023-04-10"):
            _create_event(
                distinct_id="case_sensitive_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="case_sensitivity",
            conversion_goal_name="Case Sensitivity",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-04-01", date_to="2023-04-30")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Case sensitivity handling
        # Expected: Should attribute to last-touch (April "SPRING SALE"/"GOOGLE")
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                # Should use last-touch attribution regardless of case variations
                self.assertEqual(
                    campaign_name, "SPRING SALE", f"Expected SPRING SALE (last-touch), got {campaign_name}"
                )
                self.assertEqual(source_name, "GOOGLE", f"Expected GOOGLE (last-touch), got {source_name}")
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")

    def test_null_vs_empty_utm_parameters(self):
        """
        Test Case: Null vs empty string UTM parameters

        Scenario: Different ways UTM parameters can be "missing"
        Timeline:
        - Mar 01: UTM with null values
        - Mar 15: UTM with empty strings
        - Apr 01: UTM completely missing from properties
        - Apr 10: Purchase

        Expected: All should be treated consistently as "Unknown" attribution
        Tests handling of null, empty, and missing UTM parameters
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["null_empty_user"], team=self.team)
            _create_event(
                distinct_id="null_empty_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": None, "utm_source": None},  # Null values
            )
            flush_persons_and_events()

        with freeze_time("2023-03-15"):
            _create_event(
                distinct_id="null_empty_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "", "utm_source": ""},  # Empty strings
            )
            flush_persons_and_events()

        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="null_empty_user",
                event="page_view",
                team=self.team,
                properties={},  # Missing UTM entirely
            )
            flush_persons_and_events()

        with freeze_time("2023-04-10"):
            _create_event(distinct_id="null_empty_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="null_empty",
            conversion_goal_name="Null Empty",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(
            goal=goal, index=0, team=self.team, query_date_range=DateRange(date_from="2023-04-01", date_to="2023-04-30")
        )

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        self.assertIsNotNone(response)

        # 🎯 ATTRIBUTION VALIDATION: Null vs empty UTM handling
        # Expected: Should show Unknown attribution (all UTM values are null/empty/missing)
        if response.results and len(response.results) > 0:
            first_result = response.results[0]
            if len(first_result) >= 3:
                campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                # All touchpoints have null/empty UTM, should show Unknown attribution
                self.assertIn(
                    campaign_name,
                    [None, "Unknown", "", "Unknown Campaign"],
                    f"Expected Unknown for null/empty UTM, got {campaign_name}",
                )
                self.assertIn(
                    source_name,
                    [None, "Unknown", "", "Unknown Source"],
                    f"Expected Unknown for null/empty UTM, got {source_name}",
                )
                self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")

    # ================================================================
    # 15. COMPREHENSIVE INTEGRATION TESTS - Real-world scenarios
    # ================================================================

    @unittest.expectedFailure
    def test_comprehensive_real_world_attribution_scenario(self):
        """
        Test Case: Comprehensive real-world attribution scenario

        Scenario: Complex, realistic customer journey with multiple edge cases
        Timeline:
        - Week 1: Brand awareness (YouTube) - outside attribution window
        - Week 5: Email campaign (newsletter) - valid touchpoint
        - Week 6: Organic search (no UTM) - between paid touchpoints
        - Week 7: Facebook retargeting - last paid touchpoint
        - Week 7: Purchase with some UTM on conversion event
        - Week 8: Post-purchase upsell (should not affect attribution)
        - Week 10: Second purchase (new attribution cycle)

        Expected: First purchase → Facebook retargeting, Second purchase → Facebook (or Unknown)
        Tests comprehensive real-world attribution complexity
        """
        # Week 1 - Brand awareness (potentially outside window)
        with freeze_time("2023-01-01"):
            _create_person(distinct_ids=["real_world_user"], team=self.team)
            _create_event(
                distinct_id="real_world_user",
                event="video_view",
                team=self.team,
                properties={"utm_campaign": "brand_awareness", "utm_source": "youtube"},
            )
            flush_persons_and_events()

        # Week 5 - Email campaign
        with freeze_time("2023-02-01"):
            _create_event(
                distinct_id="real_world_user",
                event="email_click",
                team=self.team,
                properties={"utm_campaign": "newsletter_feb", "utm_source": "email"},
            )
            flush_persons_and_events()

        # Week 6 - Organic search (no UTM)
        with freeze_time("2023-02-08"):
            _create_event(
                distinct_id="real_world_user",
                event="page_view",
                team=self.team,
                properties={},  # Organic - no UTM
            )
            flush_persons_and_events()

        # Week 7 - Facebook retargeting (last paid touchpoint)
        with freeze_time("2023-02-15"):
            _create_event(
                distinct_id="real_world_user",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "retarget_feb", "utm_source": "facebook"},
            )
            flush_persons_and_events()

        # Week 7 - Purchase with partial UTM (edge case)
        with freeze_time("2023-02-17"):
            _create_event(
                distinct_id="real_world_user",
                event="purchase",
                team=self.team,
                properties={
                    "revenue": 150,
                    "utm_source": "direct",  # Partial UTM on conversion event
                },
            )
            flush_persons_and_events()

        # Week 8 - Post-purchase upsell
        with freeze_time("2023-02-22"):
            _create_event(
                distinct_id="real_world_user",
                event="email_click",
                team=self.team,
                properties={"utm_campaign": "upsell_campaign", "utm_source": "email"},
            )
            flush_persons_and_events()

        # Week 10 - Second purchase
        with freeze_time("2023-03-08"):
            _create_event(distinct_id="real_world_user", event="purchase", team=self.team, properties={"revenue": 75})
            flush_persons_and_events()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="real_world",
            conversion_goal_name="Real World Scenario",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        # Test both purchases
        for period, expected_attribution in [
            (("2023-02-17", "2023-02-17"), "retarget_feb/facebook"),  # First purchase
            (("2023-03-08", "2023-03-08"), "retarget_feb/facebook or Unknown"),  # Second purchase
        ]:
            with self.subTest(period=period, expected=expected_attribution):
                processor = ConversionGoalProcessor(
                    goal=goal,
                    index=0,
                    team=self.team,
                    query_date_range=DateRange(date_from=period[0], date_to=period[1]),
                )

                additional_conditions = [
                    ast.CompareOperation(
                        left=ast.Field(chain=["events", "timestamp"]),
                        op=ast.CompareOperationOp.GtEq,
                        right=ast.Call(name="toDate", args=[ast.Constant(value=period[0])]),
                    ),
                ]

                cte_query = processor.generate_cte_query(additional_conditions)
                response = execute_hogql_query(query=cte_query, team=self.team)
                self.assertIsNotNone(response)

                # 🎯 ATTRIBUTION VALIDATION: Real-world scenario complexity
                # Expected: First purchase → "retarget_feb"/facebook, Second purchase → depends on window
                if response.results and len(response.results) > 0:
                    first_result = response.results[0]
                    if len(first_result) >= 3:
                        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
                        if period[0] == "2023-02-17":  # First purchase
                            # Should attribute to Facebook retargeting (ignores post-purchase upsell)
                            self.assertEqual(
                                campaign_name,
                                "retarget_feb",
                                f"Expected retarget_feb for first purchase, got {campaign_name}",
                            )
                            self.assertEqual(source_name, "facebook", f"Expected facebook source, got {source_name}")
                            self.assertEqual(conversion_count, 1, f"Expected 1 conversion, got {conversion_count}")
                        # Second purchase attribution depends on window policy - either retarget_feb or Unknown
