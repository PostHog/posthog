from abc import ABC, abstractmethod
from datetime import datetime
from functools import cached_property
from typing import Generic, Optional, TypeVar

import structlog

from posthog.schema import (
    ConversionGoalFilter1,
    ConversionGoalFilter2,
    ConversionGoalFilter3,
    DateRange,
    MarketingAnalyticsHelperForColumnNames,
    NodeKind,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.query_runner import AnalyticsQueryResponseProtocol, AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models.team.team import DEFAULT_CURRENCY

from products.marketing_analytics.backend.hogql_queries.constants import UNIFIED_CONVERSION_GOALS_CTE_ALIAS

from .adapters.base import MarketingSourceAdapter, QueryContext
from .adapters.factory import MarketingSourceFactory
from .conversion_goal_processor import ConversionGoalProcessor
from .conversion_goals_aggregator import ConversionGoalsAggregator
from .marketing_analytics_config import MarketingAnalyticsConfig
from .utils import convert_team_conversion_goals_to_objects

logger = structlog.get_logger(__name__)

ResponseType = TypeVar("ResponseType", bound=AnalyticsQueryResponseProtocol)


class MarketingAnalyticsBaseQueryRunner(AnalyticsQueryRunner[ResponseType], ABC, Generic[ResponseType]):
    """Base class for marketing analytics query runners with shared functionality."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = MarketingAnalyticsConfig()

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

    def _factory(self, date_range: QueryDateRange):
        """Create factory instance for the given date range"""
        context = QueryContext(
            date_range=date_range,
            team=self.team,
            base_currency=self.team.base_currency or DEFAULT_CURRENCY,
        )
        return MarketingSourceFactory(context=context)

    def _get_marketing_source_adapters(self, date_range: QueryDateRange):
        """Get marketing source adapters using the new adapter architecture"""
        try:
            factory: MarketingSourceFactory = self._factory(date_range=date_range)
            adapters = factory.create_adapters()
            valid_adapters = factory.get_valid_adapters(adapters)

            # Apply integration filter if present
            if self.query.integrationFilter and self.query.integrationFilter.integrationSourceIds:
                selected_ids = self.query.integrationFilter.integrationSourceIds
                valid_adapters = [adapter for adapter in valid_adapters if adapter.get_source_id() in selected_ids]

            return valid_adapters

        except Exception as e:
            logger.exception("Error getting marketing source adapters", error=str(e))
            return []

    def _build_campaign_cost_select(self, union_query_string: str) -> ast.SelectQuery:
        """Build the campaign_costs CTE SELECT query"""
        # Build GROUP BY using configuration - this will be overridden in aggregated queries
        group_by_exprs: list[ast.Expr] = self._get_group_by_expressions()

        # Build SELECT columns for the CTE
        select_columns: list[ast.Expr] = []

        # Only include campaign and source fields if we're grouping by them
        if group_by_exprs:
            select_columns.extend(
                [
                    ast.Field(chain=[self.config.campaign_field]),
                    ast.Field(chain=[self.config.source_field]),
                ]
            )

        select_columns.extend(
            [
                ast.Alias(
                    alias=self.config.total_cost_field,
                    expr=ast.Call(name="sum", args=[ast.Field(chain=[MarketingSourceAdapter.cost_field])]),
                ),
                ast.Alias(
                    alias=self.config.total_clicks_field,
                    expr=ast.Call(name="sum", args=[ast.Field(chain=[MarketingSourceAdapter.clicks_field])]),
                ),
                ast.Alias(
                    alias=self.config.total_impressions_field,
                    expr=ast.Call(name="sum", args=[ast.Field(chain=[MarketingSourceAdapter.impressions_field])]),
                ),
                ast.Alias(
                    alias=self.config.total_reported_conversions_field,
                    expr=ast.Call(
                        name="sum", args=[ast.Field(chain=[MarketingSourceAdapter.reported_conversion_field])]
                    ),
                ),
            ]
        )

        # Parse the union query as a subquery and wrap it in a JoinExpr
        union_subquery = parse_select(union_query_string)
        union_join_expr = ast.JoinExpr(table=union_subquery)

        # Build the CTE SELECT query
        return ast.SelectQuery(
            select=select_columns, select_from=union_join_expr, group_by=group_by_exprs if group_by_exprs else None
        )

    def _get_team_conversion_goals(self) -> list[ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3]:
        """Get conversion goals from team marketing analytics config and convert to proper objects"""
        conversion_goals = convert_team_conversion_goals_to_objects(
            self.team.marketing_analytics_config.conversion_goals, self.team.pk
        )

        if self.query.draftConversionGoal:
            conversion_goals = [self.query.draftConversionGoal, *conversion_goals]

        return conversion_goals

    def _filter_invalid_conversion_goals(
        self, conversion_goals: list[ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3]
    ) -> list[ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3]:
        """
        Filter out invalid conversion goals (e.g., those using "All Events").
        Returns only valid conversion goals.
        """
        valid_goals = []
        for goal in conversion_goals:
            # Skip "All Events" goals
            if goal.kind == NodeKind.EVENTS_NODE:
                event_name = getattr(goal, "event", None)
                if event_name is None or event_name == "":
                    logger.info(
                        "filtering_out_all_events_conversion_goal",
                        goal_name=getattr(goal, "conversion_goal_name", "Unknown"),
                    )
                    continue
            valid_goals.append(goal)

        return valid_goals

    def _create_conversion_goal_processors(
        self, conversion_goals: list[ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3]
    ) -> list:
        """Create conversion goal processors for reuse across different methods"""
        processors = []
        for index, conversion_goal in enumerate(conversion_goals):
            # Create processor if select is None (all columns) or if conversion goal columns are explicitly selected
            should_create = self.query.select is None or (
                conversion_goal.conversion_goal_name in self.query.select
                or f"{MarketingAnalyticsHelperForColumnNames.COST_PER} {conversion_goal.conversion_goal_name}"
                in self.query.select
            )
            if should_create:
                processor = ConversionGoalProcessor(
                    goal=conversion_goal, index=index, team=self.team, config=self.config
                )
                processors.append(processor)
        return processors

    def _get_where_conditions(
        self,
        date_range: QueryDateRange,
        base_conditions=None,
        include_date_range=True,
        date_field="timestamp",
        use_date_not_datetime=False,
    ) -> list[ast.Expr]:
        """Build WHERE conditions with common patterns"""
        conditions = base_conditions or []

        if include_date_range:
            # Handle date_field with table prefixes like "events.timestamp"
            date_field_chain = date_field.split(".")
            if use_date_not_datetime:
                # For conversion goals that use toDate instead of toDateTime
                # Build: date_field >= toDate('date_from')
                date_field_expr = ast.Field(chain=date_field_chain)
                from_date = ast.Call(name="toDate", args=[ast.Constant(value=date_range.date_from_str)])
                to_date = ast.Call(name="toDate", args=[ast.Constant(value=date_range.date_to_str)])

                gte_condition = ast.CompareOperation(
                    left=date_field_expr, op=ast.CompareOperationOp.GtEq, right=from_date
                )
                lte_condition = ast.CompareOperation(
                    left=date_field_expr, op=ast.CompareOperationOp.LtEq, right=to_date
                )

                conditions.extend([gte_condition, lte_condition])
            else:
                date_cast: ast.Expr
                # Build for regular datetime conditions
                if "." in date_field:
                    date_cast = ast.Call(name="toDateTime", args=[ast.Field(chain=date_field_chain)])
                else:
                    date_cast = ast.Field(chain=date_field_chain)

                from_datetime = ast.Call(name="toDateTime", args=[ast.Constant(value=date_range.date_from_str)])
                to_datetime = ast.Call(name="toDateTime", args=[ast.Constant(value=date_range.date_to_str)])

                gte_condition = ast.CompareOperation(
                    left=date_cast, op=ast.CompareOperationOp.GtEq, right=from_datetime
                )
                lte_condition = ast.CompareOperation(left=date_cast, op=ast.CompareOperationOp.LtEq, right=to_datetime)

                conditions.extend([gte_condition, lte_condition])

        return conditions

    @cached_property
    def query_compare_to_date_range(self):
        """Get the compare date range if compare filter is enabled"""
        if self.query.compareFilter is not None:
            if isinstance(self.query.compareFilter.compare_to, str):
                return QueryCompareToDateRange(
                    date_range=self.query.dateRange,
                    team=self.team,
                    interval=None,
                    now=datetime.now(),
                    compare_to=self.query.compareFilter.compare_to,
                )
            elif self.query.compareFilter.compare:
                return QueryPreviousPeriodDateRange(
                    date_range=self.query.dateRange,
                    team=self.team,
                    interval=None,
                    now=datetime.now(),
                )
        return None

    def _create_previous_period_date_range(self) -> QueryDateRange:
        """Create the date range for the previous period comparison"""
        return QueryDateRange(
            date_range=DateRange(
                date_from=self.query_compare_to_date_range.date_from().isoformat(),
                date_to=self.query_compare_to_date_range.date_to().isoformat(),
            ),
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

    def _build_complete_query_ast(
        self, union_query_string: str, processors: list, date_range: QueryDateRange
    ) -> ast.SelectQuery:
        """Build the complete query with CTEs using AST expressions"""

        # Create conversion goals aggregator if needed
        conversion_aggregator = ConversionGoalsAggregator(processors, self.config) if processors else None

        # Build the main SELECT query
        main_query = self._build_main_select_query(conversion_aggregator)

        # Build CTEs as a dictionary
        ctes: dict[str, ast.CTE] = {}

        # Add campaign_costs CTE
        campaign_cost_select = self._build_campaign_cost_select(union_query_string)
        campaign_cost_cte = ast.CTE(
            name=self.config.campaign_costs_cte_name, expr=campaign_cost_select, cte_type="subquery"
        )
        ctes[self.config.campaign_costs_cte_name] = campaign_cost_cte

        # Add unified conversion goal CTE if any
        if conversion_aggregator:
            # Check if this is an aggregated query (no GROUP BY)
            group_by_exprs = self._get_group_by_expressions()
            if not group_by_exprs:
                # For aggregated queries, create aggregated conversion goals CTE
                unified_cte = self._generate_aggregated_conversion_goals_cte(conversion_aggregator, date_range)
            else:
                # For table queries, use the normal conversion goals CTE
                unified_cte = conversion_aggregator.generate_unified_cte(date_range, self._get_where_conditions)

            if unified_cte:
                ctes[UNIFIED_CONVERSION_GOALS_CTE_ALIAS] = unified_cte

        # Add CTEs to the main query
        main_query.ctes = ctes

        return main_query

    def to_query(self) -> ast.SelectQuery:
        """Generate the HogQL query using the new adapter architecture"""
        with self.timings.measure("marketing_analytics_base_query"):
            # Get marketing source adapters
            adapters = self._get_marketing_source_adapters(date_range=self.query_date_range)

            # Build the union query using the factory
            union_query_string = self._factory(date_range=self.query_date_range).build_union_query(adapters)

            # Get conversion goals and filter out invalid ones
            conversion_goals = self._get_team_conversion_goals()
            valid_conversion_goals = self._filter_invalid_conversion_goals(conversion_goals)

            # Create processors only for valid conversion goals
            processors = (
                self._create_conversion_goal_processors(valid_conversion_goals) if valid_conversion_goals else []
            )

            # Build the complete query with CTEs using AST
            return self._build_complete_query_ast(union_query_string, processors, self.query_date_range)

    def _generate_aggregated_conversion_goals_cte(self, conversion_aggregator, date_range) -> Optional[ast.CTE]:
        """Generate aggregated conversion goals CTE without GROUP BY for aggregated queries"""
        try:
            # Get the processors
            processors = conversion_aggregator.processors
            if not processors:
                return None

            # Build select columns for aggregated conversion goals
            select_columns: list[ast.Expr] = []

            for processor in processors:
                # For aggregated queries, create a simple COUNT expression from events table
                # This counts total conversions in the date range without campaign/source matching

                # Build WHERE conditions for this conversion goal
                where_conditions = self._get_where_conditions(
                    date_range=date_range,
                    include_date_range=True,
                    date_field="events.timestamp",
                    use_date_not_datetime=False,
                )

                # Add conversion goal specific conditions
                if processor.goal.kind == "EventsNode":
                    # Event-based conversion goal
                    event_condition = ast.CompareOperation(
                        left=ast.Field(chain=["events", "event"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value=processor.goal.event),
                    )
                    where_conditions.append(event_condition)
                elif processor.goal.kind == "ActionsNode":
                    # Action-based conversion goal - more complex, skip for now
                    continue

                # For aggregated queries, use a scalar subquery to count conversions
                conversion_subquery = ast.SelectQuery(
                    select=[ast.Call(name="count", args=[])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    where=ast.And(exprs=where_conditions) if where_conditions else None,
                )

                # Use the same column naming convention as the regular conversion goals aggregator
                conversion_column_name = self.config.get_conversion_goal_column_name(processor.index)

                select_columns.append(
                    ast.Alias(
                        alias=conversion_column_name,  # This will be "conversion_0", "conversion_1", etc.
                        expr=conversion_subquery,
                    )
                )

            if not select_columns:
                return None

            # Create a simple SELECT that counts conversions directly from events
            # This gives us total conversion counts across all campaigns/sources
            aggregated_select = ast.SelectQuery(select=select_columns)

            return ast.CTE(name=UNIFIED_CONVERSION_GOALS_CTE_ALIAS, expr=aggregated_select, cte_type="subquery")

        except Exception as e:
            logger.exception("Error generating aggregated conversion goals CTE", error=str(e))
            # If we can't generate aggregated conversion goals, don't create the CTE
            return None

    def _get_group_by_expressions(self) -> list[ast.Expr]:
        """Get GROUP BY expressions"""
        return [ast.Field(chain=[field]) for field in self.config.group_by_fields]

    # Abstract methods that subclasses must implement

    @abstractmethod
    def _build_main_select_query(self, conversion_aggregator) -> ast.SelectQuery:
        """Build the main SELECT query"""
        pass

    @abstractmethod
    def _calculate(self) -> ResponseType:
        """Execute the query and return results"""
        pass
