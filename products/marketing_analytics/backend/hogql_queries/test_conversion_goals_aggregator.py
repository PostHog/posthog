import re
import uuid
import itertools
from datetime import datetime

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.schema import (
    BaseMathType,
    ConversionGoalFilter1,
    ConversionGoalFilter2,
    DateRange,
    MarketingAnalyticsBaseColumns,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_in_tests

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.preaggregation.marketing_touchpoints_sql import TRUNCATE_MARKETING_TOUCHPOINTS_TABLE_SQL
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.actions.backend.models.action import Action
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob

from .conversion_goal_processor import ConversionGoalProcessor
from .conversion_goals_aggregator import ConversionGoalsAggregator
from .marketing_analytics_config import MarketingAnalyticsConfig


def _deterministic_job_uuid_factory():
    """Monotonic 00000000-0000-0000-0000-0000000000XX so snapshots are stable."""
    counter = itertools.count(1)

    def _next() -> uuid.UUID:
        return uuid.UUID(f"00000000-0000-0000-0000-{next(counter):012d}")

    return _next


_JOB_UUID_RE = re.compile(r"'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'")


def _normalize_job_uuids(hogql: str) -> str:
    """Rewrite each distinct job UUID to 001, 002, ... in order of appearance.

    Job ids are generated per run (UUIDv7, time-based), so we normalise any UUID
    to a clean 001/002/... view that's stable across runs, without losing the
    distinction when multiple jobs appear.
    """
    seen: dict[str, int] = {}

    def _repl(match: re.Match) -> str:
        raw = match.group(0)
        if raw not in seen:
            seen[raw] = len(seen) + 1
        return f"'00000000-0000-0000-0000-{seen[raw]:012d}'"

    return _JOB_UUID_RE.sub(_repl, hogql)


class TestConversionGoalsAggregator(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_MARKETING_TOUCHPOINTS_TABLE_SQL())
        PreaggregationJob.objects.all().delete()
        # Force deterministic job_ids so the precompute snapshots are stable in CI.
        self._job_uuid_patcher = patch.object(
            PreaggregationJob._meta.get_field("id"),
            "default",
            _deterministic_job_uuid_factory(),
        )
        self._job_uuid_patcher.start()
        self.config = MarketingAnalyticsConfig.from_team(self.team)
        self.config.conversion_goal_precomputation_enabled = True
        self.date_range = QueryDateRange(
            date_range=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            team=self.team,
            interval=None,
            now=datetime(2023, 1, 31, 23, 59, 59),
        )

    def tearDown(self):
        self._job_uuid_patcher.stop()
        super().tearDown()

    def _create_test_conversion_goal(
        self,
        goal_id: str,
        goal_name: str,
        event_name: str | None = None,
        math: BaseMathType = BaseMathType.TOTAL,
        math_property: str | None = None,
    ) -> ConversionGoalFilter1:
        return ConversionGoalFilter1(
            kind="EventsNode",
            event=event_name or goal_name.lower().replace(" ", "_"),
            conversion_goal_id=goal_id,
            conversion_goal_name=goal_name,
            math=math,
            math_property=math_property,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

    def _create_test_action_goal(self, action: Action, goal_id: str, goal_name: str) -> ConversionGoalFilter2:
        return ConversionGoalFilter2(
            kind="ActionsNode",
            id=action.pk,
            conversion_goal_id=goal_id,
            conversion_goal_name=goal_name,
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

    def _create_test_processor(self, goal, index: int) -> ConversionGoalProcessor:
        return ConversionGoalProcessor(goal=goal, index=index, team=self.team, config=self.config)

    def _create_mock_additional_conditions_getter(self):
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

    def test_initialization_basic(self):
        goal1 = self._create_test_conversion_goal("goal1", "Sign Ups")
        goal2 = self._create_test_conversion_goal("goal2", "Purchases")
        processor1 = self._create_test_processor(goal1, 0)
        processor2 = self._create_test_processor(goal2, 1)
        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2], config=self.config)

        assert len(aggregator.processors) == 2
        assert aggregator.config == self.config
        assert aggregator.processors[0].index == 0
        assert aggregator.processors[1].index == 1

    def test_initialization_empty_processors(self):
        aggregator = ConversionGoalsAggregator(processors=[], config=self.config)
        assert len(aggregator.processors) == 0
        assert aggregator.config == self.config

    def test_initialization_single_processor(self):
        goal = self._create_test_conversion_goal("single_goal", "Single Goal")
        processor = self._create_test_processor(goal, 0)
        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        assert len(aggregator.processors) == 1
        assert aggregator.processors[0].goal.conversion_goal_name == "Single Goal"
        assert aggregator.processors[0].index == 0

    def test_unified_cte_empty_processors_error(self):
        aggregator = ConversionGoalsAggregator(processors=[], config=self.config)
        additional_conditions_getter = self._create_mock_additional_conditions_getter()

        with pytest.raises(ValueError, match="Cannot create unified CTE without conversion goal processors"):
            aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

    def test_unified_cte_single_processor(self):
        goal = self._create_test_conversion_goal("single_cte", "Single CTE Test")
        processor = self._create_test_processor(goal, 0)
        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)
        additional_conditions_getter = self._create_mock_additional_conditions_getter()

        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        assert isinstance(cte, ast.CTE)
        assert cte.name == "ucg"
        assert cte.cte_type == "subquery"
        assert isinstance(cte.expr, ast.SelectQuery)

        final_query = cte.expr
        assert isinstance(final_query, ast.SelectQuery)
        assert len(final_query.select) == 5  # campaign, id, source, match_key, conversion

        conversion_column = final_query.select[
            4
        ]  # Index 4 is the first conversion column (after campaign, id, source, match_key)
        assert isinstance(conversion_column, ast.Alias)
        assert conversion_column.alias == self.config.get_conversion_goal_column_name(0)
        assert isinstance(conversion_column.expr, ast.Call)
        assert conversion_column.expr.name == "sum"

    def test_unified_cte_multiple_processors(self):
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
        assert cte.name == "ucg"

        final_query = cte.expr
        assert isinstance(final_query, ast.SelectQuery)
        assert len(final_query.select) == 7  # campaign, id, source, match_key, 3 conversions

        conversion_columns = final_query.select[4:]  # Skip campaign, id, source, match_key
        assert len(conversion_columns) == 3

        for i, column in enumerate(conversion_columns):
            assert isinstance(column, ast.Alias)
            assert column.alias == self.config.get_conversion_goal_column_name(i)
            assert isinstance(column.expr, ast.Call)
            assert column.expr.name == "sum"

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_unified_cte_sql_snapshot(self):
        goal1 = self._create_test_conversion_goal("snapshot_goal1", "Snapshot Goal 1", "sign_up")
        goal2 = self._create_test_conversion_goal("snapshot_goal2", "Snapshot Goal 2", "purchase")
        processor1 = self._create_test_processor(goal1, 0)
        processor2 = self._create_test_processor(goal2, 1)
        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2], config=self.config)
        additional_conditions_getter = self._create_mock_additional_conditions_getter()

        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)
        response = execute_hogql_query(query=cte.expr, team=self.team)

        assert _normalize_job_uuids(pretty_print_in_tests(response.hogql, self.team.pk)) == self.snapshot

    def test_unified_cte_ast_structure(self):
        goal1 = self._create_test_conversion_goal("ast_goal1", "AST Goal 1", "sign_up")
        goal2 = self._create_test_conversion_goal("ast_goal2", "AST Goal 2", "purchase")
        processor1 = self._create_test_processor(goal1, 0)
        processor2 = self._create_test_processor(goal2, 1)
        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2], config=self.config)
        additional_conditions_getter = self._create_mock_additional_conditions_getter()

        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        assert isinstance(cte, ast.CTE)
        assert cte.name == "ucg"
        assert isinstance(cte.expr, ast.SelectQuery)

        final_query = cte.expr
        assert isinstance(final_query, ast.SelectQuery)
        assert len(final_query.select) == 6  # campaign, id, source, match_key, 2 conversions
        assert isinstance(final_query.select_from, ast.JoinExpr)
        # The table can be either SelectQuery (single processor) or SelectSetQuery (UNION ALL for multiple processors)
        assert isinstance(final_query.select_from.table, ast.SelectQuery | ast.SelectSetQuery)

    def test_conversion_goal_columns_single(self):
        goal = self._create_test_conversion_goal("columns_test", "Columns Test")
        processor = self._create_test_processor(goal, 0)
        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        columns = aggregator.get_conversion_goal_columns()
        assert len(columns) == 2

        goal_column = columns["Columns Test"]
        assert isinstance(goal_column, ast.Alias)
        assert goal_column.alias == "Columns Test"
        assert isinstance(goal_column.expr, ast.Field)
        expected_chain = self.config.get_unified_conversion_field_chain(self.config.get_conversion_goal_column_name(0))
        assert goal_column.expr.chain == expected_chain

        cost_column_name = f"{self.config.cost_per_prefix} Columns Test"
        cost_column = columns[cost_column_name]
        assert isinstance(cost_column, ast.Alias)
        assert cost_column.alias == cost_column_name
        assert isinstance(cost_column.expr, ast.Call)
        assert cost_column.expr.name == "round"

    def test_conversion_goal_columns_multiple(self):
        goal1 = self._create_test_conversion_goal("col_goal1", "Goal Alpha")
        goal2 = self._create_test_conversion_goal("col_goal2", "Goal Beta")
        goal3 = self._create_test_conversion_goal("col_goal3", "Goal Gamma")
        processor1 = self._create_test_processor(goal1, 0)
        processor2 = self._create_test_processor(goal2, 1)
        processor3 = self._create_test_processor(goal3, 2)
        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2, processor3], config=self.config)

        columns = aggregator.get_conversion_goal_columns()
        assert len(columns) == 6

        expected_goals = ["Goal Alpha", "Goal Beta", "Goal Gamma"]
        for goal_name in expected_goals:
            assert goal_name in columns
            assert f"{self.config.cost_per_prefix} {goal_name}" in columns

        for goal_name in expected_goals:
            cost_column_name = f"{self.config.cost_per_prefix} {goal_name}"
            cost_column = columns[cost_column_name]
            assert isinstance(cost_column.expr, ast.Call)
            assert cost_column.expr.name == "round"

            args = cost_column.expr.args
            assert len(args) == 2
            division_expr = args[0]
            assert isinstance(division_expr, ast.ArithmeticOperation)
            assert division_expr.op == ast.ArithmeticOperationOp.Div

    def test_coalesce_fallback_columns(self):
        goal = self._create_test_conversion_goal("fallback_test", "Fallback Test")
        processor = self._create_test_processor(goal, 0)
        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        fallback_columns = aggregator.get_coalesce_fallback_columns()
        assert len(fallback_columns) == 3  # campaign, id, source
        assert self.config.campaign_column_alias in fallback_columns
        assert MarketingAnalyticsBaseColumns.ID in fallback_columns
        assert self.config.source_column_alias in fallback_columns

        campaign_column = fallback_columns[self.config.campaign_column_alias]
        assert isinstance(campaign_column, ast.Alias)
        assert campaign_column.alias == self.config.campaign_column_alias
        assert isinstance(campaign_column.expr, ast.Call)
        assert campaign_column.expr.name == "coalesce"
        assert len(campaign_column.expr.args) == 3

        source_column = fallback_columns[self.config.source_column_alias]
        assert isinstance(source_column, ast.Alias)
        assert source_column.alias == self.config.source_column_alias
        assert isinstance(source_column.expr, ast.Call)
        assert source_column.expr.name == "coalesce"
        assert len(source_column.expr.args) == 3

    def test_coalesce_nullif_logic(self):
        goal = self._create_test_conversion_goal("nullif_test", "NULLIF Test")
        processor = self._create_test_processor(goal, 0)
        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        fallback_columns = aggregator.get_coalesce_fallback_columns()
        campaign_column = fallback_columns[self.config.campaign_column_alias]
        assert isinstance(campaign_column, ast.Alias)
        assert isinstance(campaign_column.expr, ast.Call)

        first_arg = campaign_column.expr.args[0]
        assert isinstance(first_arg, ast.Call)
        assert first_arg.name == "nullif"
        assert len(first_arg.args) == 2
        assert isinstance(first_arg.args[1], ast.Constant)
        assert first_arg.args[1].value == ""

        second_arg = campaign_column.expr.args[1]
        assert isinstance(second_arg, ast.Call)
        assert second_arg.name == "nullif"
        assert len(second_arg.args) == 2
        assert isinstance(second_arg.args[1], ast.Constant)
        assert second_arg.args[1].value == ""

        third_arg = campaign_column.expr.args[2]
        assert isinstance(third_arg, ast.Constant)
        assert third_arg.value == self.config.organic_campaign

    def test_integration_events_mix(self):
        events_goal1 = self._create_test_conversion_goal("integration_events1", "Events Goal 1", "sign_up")
        events_goal2 = self._create_test_conversion_goal("integration_events2", "Events Goal 2", "purchase")
        events_processor1 = self._create_test_processor(events_goal1, 0)
        events_processor2 = self._create_test_processor(events_goal2, 1)
        aggregator = ConversionGoalsAggregator(processors=[events_processor1, events_processor2], config=self.config)

        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)
        assert isinstance(cte, ast.CTE)
        assert cte.name == "ucg"

        columns = aggregator.get_conversion_goal_columns()
        assert "Events Goal 1" in columns
        assert "Events Goal 2" in columns
        assert f"{self.config.cost_per_prefix} Events Goal 1" in columns
        assert f"{self.config.cost_per_prefix} Events Goal 2" in columns

    def test_different_math_types(self):
        goal1 = self._create_test_conversion_goal("math_total", "Total Goal", "sign_up", BaseMathType.TOTAL)
        goal2 = self._create_test_conversion_goal("math_dau", "DAU Goal", "login", BaseMathType.DAU)
        goal3 = self._create_test_conversion_goal("math_total2", "Total Goal 2", "purchase", BaseMathType.TOTAL)
        processor1 = self._create_test_processor(goal1, 0)
        processor2 = self._create_test_processor(goal2, 1)
        processor3 = self._create_test_processor(goal3, 2)
        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2, processor3], config=self.config)

        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)
        assert isinstance(cte, ast.CTE)

        final_query = cte.expr
        assert isinstance(final_query, ast.SelectQuery)
        assert len(final_query.select) == 7  # campaign, id, source, match_key, 3 conversions

        columns = aggregator.get_conversion_goal_columns()
        assert len(columns) == 6

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_multiple_goals_sql_snapshot(self):
        events_goal1 = self._create_test_conversion_goal("multi_goal1", "Multi Goal 1", "purchase")
        events_goal2 = self._create_test_conversion_goal("multi_goal2", "Multi Goal 2", "sign_up")
        events_goal3 = self._create_test_conversion_goal("multi_goal3", "Multi Goal 3", "login")
        processor1 = self._create_test_processor(events_goal1, 0)
        processor2 = self._create_test_processor(events_goal2, 1)
        processor3 = self._create_test_processor(events_goal3, 2)
        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2, processor3], config=self.config)

        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)
        response = execute_hogql_query(query=cte.expr, team=self.team)

        assert _normalize_job_uuids(pretty_print_in_tests(response.hogql, self.team.pk)) == self.snapshot

    def test_aggregation_ast_validation(self):
        events_goal1 = self._create_test_conversion_goal("simple_events1", "Simple Events 1", "purchase")
        events_goal2 = self._create_test_conversion_goal("simple_events2", "Simple Events 2", "sign_up")
        events_goal3 = self._create_test_conversion_goal("simple_events3", "Simple Events 3", "login")
        processor1 = self._create_test_processor(events_goal1, 0)
        processor2 = self._create_test_processor(events_goal2, 1)
        processor3 = self._create_test_processor(events_goal3, 2)
        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2, processor3], config=self.config)

        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        assert isinstance(cte, ast.CTE)
        assert cte.name == "ucg"

        final_query = cte.expr
        assert isinstance(final_query, ast.SelectQuery)
        assert len(final_query.select) == 7  # campaign, id, source, match_key, 3 conversions

        conversion_columns = final_query.select[4:]  # Skip campaign, id, source, match_key
        expected_names = [
            self.config.get_conversion_goal_column_name(0),
            self.config.get_conversion_goal_column_name(1),
            self.config.get_conversion_goal_column_name(2),
        ]
        actual_names = [col.alias for col in conversion_columns if isinstance(col, ast.Alias)]
        assert actual_names == expected_names

    def test_empty_goal_name(self):
        goal = ConversionGoalFilter1(
            kind="EventsNode",
            event="test_event",
            conversion_goal_id="empty_name_test",
            conversion_goal_name="",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )
        processor = self._create_test_processor(goal, 0)
        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        columns = aggregator.get_conversion_goal_columns()
        assert "" in columns
        assert f"{self.config.cost_per_prefix} " in columns

    def test_high_processor_indices(self):
        goal = self._create_test_conversion_goal("high_index_test", "High Index Test")
        processor = self._create_test_processor(goal, 999)
        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)
        assert isinstance(cte, ast.CTE)

        final_query = cte.expr
        assert isinstance(final_query, ast.SelectQuery)
        conversion_column = final_query.select[
            4
        ]  # Index 4 is the first conversion column (after campaign, id, source, match_key)
        assert isinstance(conversion_column, ast.Alias)
        assert conversion_column.alias == self.config.get_conversion_goal_column_name(999)
        assert isinstance(conversion_column.expr, ast.Call)
        assert conversion_column.expr.name == "sum"

    def test_duplicate_goal_names(self):
        goal1 = self._create_test_conversion_goal("dup1", "Duplicate Goal")
        goal2 = self._create_test_conversion_goal("dup2", "Duplicate Goal")
        processor1 = self._create_test_processor(goal1, 0)
        processor2 = self._create_test_processor(goal2, 1)
        aggregator = ConversionGoalsAggregator(processors=[processor1, processor2], config=self.config)

        columns = aggregator.get_conversion_goal_columns()
        assert "Duplicate Goal" in columns
        assert f"{self.config.cost_per_prefix} Duplicate Goal" in columns

    def test_many_processors(self):
        processors = []
        for i in range(10):
            goal = self._create_test_conversion_goal(f"perf_goal_{i}", f"Performance Goal {i}")
            processor = self._create_test_processor(goal, i)
            processors.append(processor)
        aggregator = ConversionGoalsAggregator(processors=processors, config=self.config)

        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)
        assert isinstance(cte, ast.CTE)

        final_query = cte.expr
        assert isinstance(final_query, ast.SelectQuery)
        assert (
            len(final_query.select) == 14
        )  # 4 grouping fields (campaign, id, source, match_key) + 10 conversion goals

        columns = aggregator.get_conversion_goal_columns()
        assert len(columns) == 20

        fallback_columns = aggregator.get_coalesce_fallback_columns()
        assert len(fallback_columns) == 3  # campaign, id, source

    def test_attribution_compatibility(self):
        goal = self._create_test_conversion_goal("attribution_test", "Attribution Test", "purchase")
        processor = self._create_test_processor(goal, 0)
        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        assert isinstance(cte, ast.CTE)
        assert cte.name == "ucg"

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_campaign_name_mapping_sql_generation(self):
        """Test that campaign name mappings generate correct SQL with nested CASE statements"""
        # Configure campaign name mappings for multiple sources
        self.team.marketing_analytics_config.campaign_name_mappings = {
            "GoogleAds": {
                "Spring Sale 2024": ["spring_sale_2024", "spring-sale-2024", "SPRING_SALE"],
                "Black Friday": ["bf_2024", "blackfriday", "BF-PROMO"],
            },
            "MetaAds": {
                "Spring Sale 2024": ["spring_sale_fb", "SpringSaleFB"],
                "Summer Campaign": ["summer_2024", "SUMMER_PROMO"],
            },
        }
        self.team.marketing_analytics_config.save()

        goal = self._create_test_conversion_goal("mapping_sql_test", "Mapping SQL Test", "purchase")
        processor = self._create_test_processor(goal, 0)
        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        # Execute to get the SQL string
        response = execute_hogql_query(query=cte.expr, team=self.team)

        assert _normalize_job_uuids(pretty_print_in_tests(response.hogql, self.team.pk)) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_campaign_name_mapping_single_source_sql(self):
        """Test campaign name mapping for a single data source"""
        self.team.marketing_analytics_config.campaign_name_mappings = {
            "GoogleAds": {
                "Clean Campaign Name": ["messy_campaign_1", "messy_campaign_2", "MESSY_CAMPAIGN_3"],
            }
        }
        self.team.marketing_analytics_config.save()

        goal = self._create_test_conversion_goal("single_source_mapping", "Single Source Mapping", "conversion")
        processor = self._create_test_processor(goal, 0)
        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        response = execute_hogql_query(query=cte.expr, team=self.team)

        assert _normalize_job_uuids(pretty_print_in_tests(response.hogql, self.team.pk)) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_campaign_name_mapping_no_mappings(self):
        """Test that when no mappings are configured, the query uses original campaign names"""
        self.team.marketing_analytics_config.campaign_name_mappings = {}
        self.team.marketing_analytics_config.save()

        goal = self._create_test_conversion_goal("no_mapping_test", "No Mapping Test", "purchase")
        processor = self._create_test_processor(goal, 0)
        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        response = execute_hogql_query(query=cte.expr, team=self.team)

        assert _normalize_job_uuids(pretty_print_in_tests(response.hogql, self.team.pk)) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_campaign_name_mapping_integration_with_events(self):
        """Test campaign name mapping SQL generation with actual events to verify mapping works end-to-end"""
        # Configure campaign name mappings for GoogleAds
        self.team.marketing_analytics_config.campaign_name_mappings = {
            "GoogleAds": {
                "Spring Sale 2024": ["spring_sale_2024", "spring-sale-2024"],
                "Holiday Promo": ["holiday_campaign", "holiday_promo"],
            }
        }
        self.team.marketing_analytics_config.save()

        # Create conversion goal
        goal = self._create_test_conversion_goal("integration_test", "Integration Test", "purchase")
        processor = self._create_test_processor(goal, 0)
        aggregator = ConversionGoalsAggregator(processors=[processor], config=self.config)

        additional_conditions_getter = self._create_mock_additional_conditions_getter()
        cte = aggregator.generate_unified_cte(self.date_range, additional_conditions_getter)

        # Execute the query to get the SQL (but don't worry about results due to memory limits)
        response = execute_hogql_query(query=cte.expr, team=self.team)

        # Verify the SQL contains campaign name mapping logic
        assert _normalize_job_uuids(pretty_print_in_tests(response.hogql, self.team.pk)) == self.snapshot

        # Verify that the SQL contains the expected campaign name mapping logic
        sql_string = pretty_print_in_tests(response.hogql, self.team.pk)

        # Check that the SQL contains multiIf with campaign name mapping
        assert "multiIf" in sql_string, "SQL should contain multiIf for campaign name mapping"
        assert "Spring Sale 2024" in sql_string, "SQL should contain mapped campaign name"
        assert "Holiday Promo" in sql_string, "SQL should contain mapped campaign name"
        assert "spring_sale_2024" in sql_string, "SQL should contain original campaign name in mapping"
        assert "holiday_campaign" in sql_string, "SQL should contain original campaign name in mapping"
