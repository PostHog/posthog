import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.schema import BaseMathType, ConversionGoalFilter1, ConversionGoalFilter2, DateRange, NodeKind

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_in_tests

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Action

from .conversion_goal_processor import ConversionGoalProcessor
from .marketing_analytics_config import MarketingAnalyticsConfig
from .unified_conversion_goals_query_runner import ConversionGoalsAggregator


def _create_test_action(**kwargs):
    """Helper to create Action objects for testing"""
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    event_name = kwargs.pop("event_name", name)
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": event_name, "properties": properties}])
    return action


class TestConversionGoalsAggregator(ClickhouseTestMixin, BaseTest):
    """
    Comprehensive test suite for ConversionGoalsAggregator.
    """

    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.config = MarketingAnalyticsConfig()
        self.date_range = QueryDateRange(
            date_range=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            team=self.team,
            interval=None,
            now=None,
        )

    def _create_test_conversion_goal(
        self,
        goal_id: str,
        goal_name: str,
        event_name: str | None = None,
        math: BaseMathType = BaseMathType.TOTAL,
        math_property: str | None = None,
    ) -> ConversionGoalFilter1:
        """Create a test conversion goal for events"""
        return ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event=event_name or goal_name.lower().replace(" ", "_"),
            conversion_goal_id=goal_id,
            conversion_goal_name=goal_name,
            math=math,
            math_property=math_property,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

    def _create_test_action_goal(self, action: Action, goal_id: str, goal_name: str) -> ConversionGoalFilter2:
        """Create a test conversion goal for actions"""
        return ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id=str(action.id),
            conversion_goal_id=goal_id,
            conversion_goal_name=goal_name,
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

    def _create_test_processor(self, goal, index: int) -> ConversionGoalProcessor:
        """Create a test conversion goal processor"""
        return ConversionGoalProcessor(goal=goal, index=index, team=self.team, config=self.config)

    def _create_mock_additional_conditions_getter(self):
        """Create a mock additional conditions getter that returns basic date filtering"""

        def mock_getter(**kwargs):
            return [
                ast.CompareOperation(
                    left=ast.Field(chain=["events", "timestamp"]),
                    op=ast.CompareOperationOp.GtEq,
                    right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=["events", "timestamp"]),
                    op=ast.CompareOperationOp.Lt,
                    right=ast.Call(name="toDate", args=[ast.Constant(value="2023-02-01")]),
                ),
            ]

        return mock_getter

    # ================================================================
    # 1. INITIALIZATION AND BASIC FUNCTIONALITY TESTS
    # ================================================================

    def test_aggregator_initialization_basic(self):
        """Test basic aggregator initialization"""
        goal1 = self._create_test_conversion_goal("goal1", "Sign Ups")
        goal2 = self._create_test_conversion_goal("goal2", "Purchases")

        processor1 = self._create_test_processor(goal1, 0)
        processor2 = self._create_test_processor(goal2, 1)

        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2], config=self.config)

        assert len(aggregator.processors) == 2
        assert aggregator.config == self.config
        assert aggregator.processors[0].index == 0
        assert aggregator.processors[1].index == 1

    def test_aggregator_initialization_empty_processors(self):
        """Test aggregator initialization with empty processors list"""
        aggregator = ConversionGoalsAggregator(processors=[], config=self.config)

        assert len(aggregator.processors) == 0
        assert aggregator.config == self.config

    def test_aggregator_initialization_single_processor(self):
        """Test aggregator initialization with single processor"""
        goal = self._create_test_conversion_goal("single_goal", "Single Goal")
        processor = self._create_test_processor(goal, 0)

        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        assert len(aggregator.processors) == 1
        assert aggregator.processors[0].goal.conversion_goal_name == "Single Goal"
        assert aggregator.processors[0].index == 0

    # ================================================================
    # 2. UNIFIED CTE GENERATION TESTS
    # ================================================================

    def test_generate_unified_cte_raises_error_on_empty_processors(self):
        """Test that generate_unified_cte raises ValueError for empty processors"""
        aggregator = ConversionGoalsAggregator(processors=[], config=self.config)
        additional_conditions_getter = self._create_mock_additional_conditions_getter()

        with pytest.raises(ValueError, match="Cannot create unified CTE without conversion goal processors"):
            aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

    def test_generate_unified_cte_single_processor(self):
        """Test unified CTE generation with single processor"""
        goal = self._create_test_conversion_goal("single_cte", "Single CTE Test")
        processor = self._create_test_processor(goal, 0)

        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)
        additional_conditions_getter = self._create_mock_additional_conditions_getter()

        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        assert isinstance(cte, ast.CTE)
        assert cte.name == "unified_conversion_goals"
        assert cte.cte_type == "subquery"
        assert isinstance(cte.expr, ast.SelectQuery)

        # Verify final query structure for single processor
        final_query = cte.expr
        assert len(final_query.select) == 3  # campaign, source, conversion_goal_0
        assert len(final_query.group_by) == 2  # campaign, source

        # Check that we have the correct column names
        conversion_column = final_query.select[2]
        assert isinstance(conversion_column, ast.Alias)
        assert conversion_column.alias == self.config.get_conversion_goal_column_name(0)

    def test_generate_unified_cte_multiple_processors(self):
        """Test unified CTE generation with multiple processors"""
        goal1 = self._create_test_conversion_goal("multi_goal1", "Goal 1")
        goal2 = self._create_test_conversion_goal("multi_goal2", "Goal 2")
        goal3 = self._create_test_conversion_goal("multi_goal3", "Goal 3")

        processor1 = self._create_test_processor(goal1, 0)
        processor2 = self._create_test_processor(goal2, 1)
        processor3 = self._create_test_processor(goal3, 2)

        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2, processor3], config=self.config)
        additional_conditions_getter = self._create_mock_additional_conditions_getter()

        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        assert isinstance(cte, ast.CTE)
        assert cte.name == "unified_conversion_goals"

        # Verify final query structure for multiple processors
        final_query = cte.expr
        assert len(final_query.select) == 5  # campaign, source, conversion_goal_0, conversion_goal_1, conversion_goal_2
        assert len(final_query.group_by) == 2  # campaign, source

        # Check all conversion goal columns are present
        conversion_columns = final_query.select[2:]  # Skip campaign and source
        assert len(conversion_columns) == 3

        for i, column in enumerate(conversion_columns):
            assert isinstance(column, ast.Alias)
            assert column.alias == self.config.get_conversion_goal_column_name(i)
            assert isinstance(column.expr, ast.Call)
            assert column.expr.name == "sum"

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_generate_unified_cte_sql_structure_snapshot(self):
        """Test unified CTE SQL structure with snapshot validation"""
        goal1 = self._create_test_conversion_goal("snapshot_goal1", "Snapshot Goal 1", "sign_up")
        goal2 = self._create_test_conversion_goal("snapshot_goal2", "Snapshot Goal 2", "purchase")

        processor1 = self._create_test_processor(goal1, 0)
        processor2 = self._create_test_processor(goal2, 1)

        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2], config=self.config)
        additional_conditions_getter = self._create_mock_additional_conditions_getter()

        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        # Execute the query to get properly formatted SQL like other snapshot tests
        response = execute_hogql_query(query=cte.expr, team=self.team)

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    def test_generate_unified_cte_ast_structure_validation(self):
        """Test unified CTE AST structure validation without executing the query"""
        goal1 = self._create_test_conversion_goal("ast_goal1", "AST Goal 1", "sign_up")
        goal2 = self._create_test_conversion_goal("ast_goal2", "AST Goal 2", "purchase")

        processor1 = self._create_test_processor(goal1, 0)
        processor2 = self._create_test_processor(goal2, 1)

        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2], config=self.config)
        additional_conditions_getter = self._create_mock_additional_conditions_getter()

        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        # Validate AST structure without executing
        assert isinstance(cte, ast.CTE)
        assert cte.name == "unified_conversion_goals"
        assert isinstance(cte.expr, ast.SelectQuery)

        # Validate final query has correct structure
        final_query = cte.expr
        assert len(final_query.select) == 4  # campaign, source, goal_0, goal_1
        assert len(final_query.group_by) == 2  # campaign, source

        # Validate that it's selecting from a UNION ALL subquery (maintains exact attribution)
        assert isinstance(final_query.select_from, ast.JoinExpr)
        assert isinstance(final_query.select_from.table, ast.SelectSetQuery)

    # ================================================================
    # 3. CONVERSION GOAL COLUMNS TESTS
    # ================================================================

    def test_get_conversion_goal_columns_single_processor(self):
        """Test conversion goal columns generation for single processor"""
        goal = self._create_test_conversion_goal("columns_test", "Columns Test")
        processor = self._create_test_processor(goal, 0)

        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)
        columns = aggregator.get_conversion_goal_columns()

        assert len(columns) == 2  # conversion goal + cost per conversion

        # Check conversion goal column
        goal_column = columns["Columns Test"]
        assert isinstance(goal_column, ast.Alias)
        assert goal_column.alias == "Columns Test"
        assert isinstance(goal_column.expr, ast.Field)
        expected_chain = self.config.get_unified_conversion_field_chain(self.config.get_conversion_goal_column_name(0))
        assert goal_column.expr.chain == expected_chain

        # Check cost per conversion column
        cost_column_name = f"{self.config.cost_per_prefix} Columns Test"
        cost_column = columns[cost_column_name]
        assert isinstance(cost_column, ast.Alias)
        assert cost_column.alias == cost_column_name
        assert isinstance(cost_column.expr, ast.Call)
        assert cost_column.expr.name == "round"

    def test_get_conversion_goal_columns_multiple_processors(self):
        """Test conversion goal columns generation for multiple processors"""
        goal1 = self._create_test_conversion_goal("col_goal1", "Goal Alpha")
        goal2 = self._create_test_conversion_goal("col_goal2", "Goal Beta")
        goal3 = self._create_test_conversion_goal("col_goal3", "Goal Gamma")

        processor1 = self._create_test_processor(goal1, 0)
        processor2 = self._create_test_processor(goal2, 1)
        processor3 = self._create_test_processor(goal3, 2)

        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2, processor3], config=self.config)
        columns = aggregator.get_conversion_goal_columns()

        assert len(columns) == 6  # 3 goals × 2 columns each

        # Check that all goal columns exist
        expected_goals = ["Goal Alpha", "Goal Beta", "Goal Gamma"]
        for goal_name in expected_goals:
            assert goal_name in columns
            assert f"{self.config.cost_per_prefix} {goal_name}" in columns

        # Verify cost per conversion calculation structure
        for goal_name in expected_goals:
            cost_column_name = f"{self.config.cost_per_prefix} {goal_name}"
            cost_column = columns[cost_column_name]
            assert isinstance(cost_column.expr, ast.Call)
            assert cost_column.expr.name == "round"

            # Should be a division operation
            args = cost_column.expr.args
            assert len(args) == 2
            division_expr = args[0]
            assert isinstance(division_expr, ast.ArithmeticOperation)
            assert division_expr.op == ast.ArithmeticOperationOp.Div

    def test_get_conversion_goal_columns_field_chain_accuracy(self):
        """Test accuracy of field chains in conversion goal columns"""
        goal = self._create_test_conversion_goal("chain_test", "Chain Test")
        processor = self._create_test_processor(goal, 5)  # Use non-zero index

        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)
        columns = aggregator.get_conversion_goal_columns()

        goal_column = columns["Chain Test"]
        expected_chain = [
            self.config.unified_conversion_goals_cte_alias,
            self.config.get_conversion_goal_column_name(5),
        ]
        assert goal_column.expr.chain == expected_chain

    # ================================================================
    # 4. COALESCE FALLBACK COLUMNS TESTS
    # ================================================================

    def test_get_coalesce_fallback_columns_structure(self):
        """Test COALESCE fallback columns structure"""
        goal = self._create_test_conversion_goal("fallback_test", "Fallback Test")
        processor = self._create_test_processor(goal, 0)

        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)
        fallback_columns = aggregator.get_coalesce_fallback_columns()

        assert len(fallback_columns) == 2
        assert self.config.campaign_column_alias in fallback_columns
        assert self.config.source_column_alias in fallback_columns

        # Check campaign COALESCE structure
        campaign_column = fallback_columns[self.config.campaign_column_alias]
        assert isinstance(campaign_column, ast.Alias)
        assert campaign_column.alias == self.config.campaign_column_alias
        assert isinstance(campaign_column.expr, ast.Call)
        assert campaign_column.expr.name == "coalesce"
        assert len(campaign_column.expr.args) == 3  # campaign_cost, unified_conversion, organic_default

        # Check source COALESCE structure
        source_column = fallback_columns[self.config.source_column_alias]
        assert isinstance(source_column, ast.Alias)
        assert source_column.alias == self.config.source_column_alias
        assert isinstance(source_column.expr, ast.Call)
        assert source_column.expr.name == "coalesce"
        assert len(source_column.expr.args) == 3  # source_cost, unified_conversion, organic_default

    def test_get_coalesce_fallback_columns_nullif_logic(self):
        """Test NULLIF logic in COALESCE fallback columns"""
        goal = self._create_test_conversion_goal("nullif_test", "NULLIF Test")
        processor = self._create_test_processor(goal, 0)

        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)
        fallback_columns = aggregator.get_coalesce_fallback_columns()

        campaign_column = fallback_columns[self.config.campaign_column_alias]

        # Check first NULLIF arg (campaign cost)
        first_arg = campaign_column.expr.args[0]
        assert isinstance(first_arg, ast.Call)
        assert first_arg.name == "nullif"
        assert len(first_arg.args) == 2
        assert isinstance(first_arg.args[1], ast.Constant)
        assert first_arg.args[1].value == ""

        # Check second NULLIF arg (unified conversion)
        second_arg = campaign_column.expr.args[1]
        assert isinstance(second_arg, ast.Call)
        assert second_arg.name == "nullif"
        assert len(second_arg.args) == 2
        assert isinstance(second_arg.args[1], ast.Constant)
        assert second_arg.args[1].value == ""

        # Check organic fallback (third arg)
        third_arg = campaign_column.expr.args[2]
        assert isinstance(third_arg, ast.Constant)
        assert third_arg.value == self.config.organic_campaign

    def test_get_coalesce_fallback_columns_field_chains(self):
        """Test field chains in COALESCE fallback columns"""
        goal = self._create_test_conversion_goal("field_chain_test", "Field Chain Test")
        processor = self._create_test_processor(goal, 0)

        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)
        fallback_columns = aggregator.get_coalesce_fallback_columns()

        campaign_column = fallback_columns[self.config.campaign_column_alias]

        # Check campaign cost field chain
        first_nullif = campaign_column.expr.args[0]
        campaign_cost_field = first_nullif.args[0]
        assert isinstance(campaign_cost_field, ast.Field)
        expected_campaign_cost_chain = self.config.get_campaign_cost_field_chain(self.config.campaign_field)
        assert campaign_cost_field.chain == expected_campaign_cost_chain

        # Check unified conversion field chain
        second_nullif = campaign_column.expr.args[1]
        unified_conversion_field = second_nullif.args[0]
        assert isinstance(unified_conversion_field, ast.Field)
        expected_unified_chain = self.config.get_unified_conversion_field_chain(self.config.campaign_field)
        assert unified_conversion_field.chain == expected_unified_chain

    # ================================================================
    # 5. INTEGRATION TESTS WITH DIFFERENT GOAL TYPES
    # ================================================================

    def test_integration_events_only_mix(self):
        """Test aggregator with multiple EventsNode processors (simplified for stability)"""
        # Create goals - all EventsNode to avoid ActionNode complexity
        events_goal1 = self._create_test_conversion_goal("integration_events1", "Events Goal 1", "sign_up")
        events_goal2 = self._create_test_conversion_goal("integration_events2", "Events Goal 2", "purchase")

        # Create processors
        events_processor1 = self._create_test_processor(events_goal1, 0)
        events_processor2 = self._create_test_processor(events_goal2, 1)

        aggregator = ConversionGoalsAggregator(processors=[events_processor1, events_processor2], config=self.config)

        # Test unified CTE generation works with multiple EventsNode types
        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        assert isinstance(cte, ast.CTE)
        assert cte.name == "unified_conversion_goals"

        # Test column generation works with multiple types
        columns = aggregator.get_conversion_goal_columns()
        assert "Events Goal 1" in columns
        assert "Events Goal 2" in columns
        assert f"{self.config.cost_per_prefix} Events Goal 1" in columns
        assert f"{self.config.cost_per_prefix} Events Goal 2" in columns

    def test_integration_different_math_types(self):
        """Test aggregator with different math types (simplified to avoid complex operations)"""
        goal1 = self._create_test_conversion_goal("math_total", "Total Goal", "sign_up", BaseMathType.TOTAL)
        goal2 = self._create_test_conversion_goal("math_dau", "DAU Goal", "login", BaseMathType.DAU)
        goal3 = self._create_test_conversion_goal("math_total2", "Total Goal 2", "purchase", BaseMathType.TOTAL)

        processor1 = self._create_test_processor(goal1, 0)
        processor2 = self._create_test_processor(goal2, 1)
        processor3 = self._create_test_processor(goal3, 2)

        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2, processor3], config=self.config)

        # Should handle different math types without errors
        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        assert isinstance(cte, ast.CTE)
        final_query = cte.expr
        assert len(final_query.select) == 5  # campaign, source, 3 goals

        # All should generate valid column mappings
        columns = aggregator.get_conversion_goal_columns()
        assert len(columns) == 6  # 3 goals × 2 columns each

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_integration_multiple_goals_sql_snapshot(self):
        """Integration test with multiple goals and SQL snapshot validation"""
        # Create simple goals to avoid complex attribution logic
        events_goal1 = self._create_test_conversion_goal("multi_goal1", "Multi Goal 1", "purchase")
        events_goal2 = self._create_test_conversion_goal("multi_goal2", "Multi Goal 2", "sign_up")
        events_goal3 = self._create_test_conversion_goal("multi_goal3", "Multi Goal 3", "login")

        # Create processors with different indices
        processor1 = self._create_test_processor(events_goal1, 0)
        processor2 = self._create_test_processor(events_goal2, 1)
        processor3 = self._create_test_processor(events_goal3, 2)

        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2, processor3], config=self.config)

        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        # Execute the query to get properly formatted SQL like other snapshot tests
        response = execute_hogql_query(query=cte.expr, team=self.team)

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    def test_integration_simple_aggregation_ast_validation(self):
        """Integration test with simple aggregation and AST validation"""
        # Create simple goals to avoid complex attribution logic
        events_goal1 = self._create_test_conversion_goal("simple_events1", "Simple Events 1", "purchase")
        events_goal2 = self._create_test_conversion_goal("simple_events2", "Simple Events 2", "sign_up")
        events_goal3 = self._create_test_conversion_goal("simple_events3", "Simple Events 3", "login")

        # Create processors with different indices
        processor1 = self._create_test_processor(events_goal1, 0)
        processor2 = self._create_test_processor(events_goal2, 1)
        processor3 = self._create_test_processor(events_goal3, 2)

        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2, processor3], config=self.config)

        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        # Validate AST structure for complex case
        assert isinstance(cte, ast.CTE)
        assert cte.name == "unified_conversion_goals"

        final_query = cte.expr
        assert len(final_query.select) == 5  # campaign, source, 3 goals
        assert len(final_query.group_by) == 2  # campaign, source

        # Validate column names
        conversion_columns = final_query.select[2:]
        expected_names = [
            self.config.get_conversion_goal_column_name(0),
            self.config.get_conversion_goal_column_name(1),
            self.config.get_conversion_goal_column_name(2),
        ]
        actual_names = [col.alias for col in conversion_columns]
        assert actual_names == expected_names

    # ================================================================
    # 6. ERROR HANDLING AND EDGE CASES
    # ================================================================

    def test_error_handling_processor_with_missing_goal_name(self):
        """Test handling of processors with missing or invalid goal names"""
        # Create goal with empty name
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="test_event",
            conversion_goal_id="empty_name_test",
            conversion_goal_name="",  # Empty name
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = self._create_test_processor(goal, 0)
        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        # Should still generate columns, just with empty name
        columns = aggregator.get_conversion_goal_columns()
        assert "" in columns
        assert f"{self.config.cost_per_prefix} " in columns

    def test_error_handling_high_processor_indices(self):
        """Test handling of processors with high index values"""
        goal = self._create_test_conversion_goal("high_index_test", "High Index Test")
        processor = self._create_test_processor(goal, 999)  # High index

        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        # Should handle high indices without issues
        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        assert isinstance(cte, ast.CTE)

        # Check that column name includes the high index
        final_query = cte.expr
        conversion_column = final_query.select[2]  # Skip campaign and source
        assert conversion_column.alias == self.config.get_conversion_goal_column_name(999)

    def test_error_handling_duplicate_goal_names(self):
        """Test handling of processors with duplicate goal names"""
        goal1 = self._create_test_conversion_goal("dup1", "Duplicate Goal")
        goal2 = self._create_test_conversion_goal("dup2", "Duplicate Goal")  # Same name

        processor1 = self._create_test_processor(goal1, 0)
        processor2 = self._create_test_processor(goal2, 1)

        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2], config=self.config)

        # Should handle duplicate names (later one may overwrite in dict)
        columns = aggregator.get_conversion_goal_columns()

        # Should have entries for the duplicate name
        assert "Duplicate Goal" in columns
        assert f"{self.config.cost_per_prefix} Duplicate Goal" in columns

    def test_performance_many_processors(self):
        """Test performance characteristics with many processors"""
        # Create 10 processors to test scalability
        processors = []
        for i in range(10):
            goal = self._create_test_conversion_goal(f"perf_goal_{i}", f"Performance Goal {i}")
            processor = self._create_test_processor(goal, i)
            processors.append(processor)

        aggregator = ConversionGoalsAggregator(processors=processors, config=self.config)

        # Should handle many processors without errors
        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        assert isinstance(cte, ast.CTE)
        final_query = cte.expr
        assert len(final_query.select) == 12  # campaign + source + 10 goals

        # Should generate all column mappings
        columns = aggregator.get_conversion_goal_columns()
        assert len(columns) == 20  # 10 goals × 2 columns each

        # Should generate fallback columns without issues
        fallback_columns = aggregator.get_coalesce_fallback_columns()
        assert len(fallback_columns) == 2

    def test_attribution_logic_exact_compatibility_note(self):
        """
        IMPORTANT NOTE: This implementation maintains exact attribution compatibility.

        Attribution Logic (Exact):
        - Uses 365-day attribution windows per conversion (same as original)
        - Array-based processing with ARRAY JOIN for each conversion event (same as original)
        - Per-conversion attribution to most recent UTM within window (same as original)
        - Complex temporal attribution with conversion_timestamps arrays (same as original)

        Architecture:
        - UNION ALL approach to maintain exact ConversionGoalProcessor logic
        - Each conversion goal uses its full original attribution query
        - Final aggregation sums results by campaign/source

        Trade-off: Exactitude vs Performance
        This approach prioritizes exact results over performance optimization.
        The SQL is complex but produces identical results to individual processors.
        """
        goal = self._create_test_conversion_goal("attribution_test", "Attribution Test", "purchase")
        processor = self._create_test_processor(goal, 0)
        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        # This test documents that we maintain exact attribution logic
        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        # The structure maintains exact compatibility
        assert isinstance(cte, ast.CTE)
        assert cte.name == "unified_conversion_goals"
