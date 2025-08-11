from functools import cached_property
from datetime import datetime
import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models.team.team import DEFAULT_CURRENCY
from posthog.schema import (
    ConversionGoalFilter1,
    ConversionGoalFilter2,
    ConversionGoalFilter3,
    DateRange,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsHelperForColumnNames,
    MarketingAnalyticsTableQuery,
    MarketingAnalyticsTableQueryResponse,
    CachedMarketingAnalyticsTableQueryResponse,
)
from typing import cast, Literal
from .conversion_goal_processor import ConversionGoalProcessor

from .constants import (
    BASE_COLUMN_MAPPING,
    CAMPAIGN_COST_CTE_NAME,
    DEFAULT_LIMIT,
    PAGINATION_EXTRA,
    TOTAL_CLICKS_FIELD,
    TOTAL_COST_FIELD,
    TOTAL_IMPRESSIONS_FIELD,
)
from .utils import (
    convert_team_conversion_goals_to_objects,
)
from .adapters.factory import MarketingSourceFactory
from .adapters.base import QueryContext, MarketingSourceAdapter

logger = structlog.get_logger(__name__)


class MarketingAnalyticsTableQueryRunner(QueryRunner):
    query: MarketingAnalyticsTableQuery
    response: MarketingAnalyticsTableQueryResponse
    cached_response: CachedMarketingAnalyticsTableQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context, limit=self.query.limit, offset=self.query.offset
        )

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

        # Create query context for all adapters
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

            logger.info(f"Found {len(valid_adapters)} valid marketing source adapters")

            return valid_adapters

        except Exception as e:
            logger.exception("Error getting marketing source adapters", error=str(e))
            return []

    def to_query(self) -> ast.SelectQuery:
        """Generate the HogQL query using the new adapter architecture"""
        with self.timings.measure("marketing_analytics_table_query"):
            # Get marketing source adapters
            adapters = self._get_marketing_source_adapters(date_range=self.query_date_range)

            # Build the union query using the factory
            union_query_string = self._factory(date_range=self.query_date_range).build_union_query(adapters)

            # Get conversion goals and create processors
            conversion_goals = self._get_team_conversion_goals()
            processors = self._create_conversion_goal_processors(conversion_goals) if conversion_goals else []

            # Build the complete query with CTEs using AST
            return self._build_complete_query_ast(union_query_string, processors, self.query_date_range)

    def _build_complete_query_ast(
        self, union_query_string: str, processors: list, date_range: QueryDateRange
    ) -> ast.SelectQuery:
        """Build the complete query with CTEs using AST expressions"""

        # Build the main SELECT query
        main_query = self._build_select_query(processors)

        # Build CTEs as a dictionary
        ctes: dict[str, ast.CTE] = {}

        # Add campaign_costs CTE
        campaign_cost_select = self._build_campaign_cost_select(union_query_string)
        campaign_cost_cte = ast.CTE(name=CAMPAIGN_COST_CTE_NAME, expr=campaign_cost_select, cte_type="subquery")
        ctes[CAMPAIGN_COST_CTE_NAME] = campaign_cost_cte

        # Add conversion goal CTEs if any
        if processors:
            for processor in processors:
                # Build additional conditions (date range and global filters)
                date_field = processor.get_date_field()
                additional_conditions = self._get_where_conditions(
                    date_range=date_range,
                    include_date_range=True,
                    date_field=date_field,
                    use_date_not_datetime=True,  # Conversion goals use toDate instead of toDateTime
                )

                # Generate CTE
                cte_alias = processor.generate_cte_query_expr(additional_conditions)
                cte_name = processor.get_cte_name()
                cte = ast.CTE(name=cte_name, expr=cte_alias.expr, cte_type="subquery")
                ctes[cte_name] = cte

        # Add CTEs to the main query
        main_query.ctes = ctes

        return main_query

    def calculate(self) -> MarketingAnalyticsTableQueryResponse:
        """Execute the query and return results with pagination support"""
        from posthog.hogql.query import execute_hogql_query

        query: ast.SelectQuery
        if self.query.compareFilter is not None and self.query.compareFilter.compare:
            query = self.calculate_with_compare()
        else:
            query = self.calculate_without_compare()

        response = execute_hogql_query(
            query_type="marketing_analytics_table_query",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        results = response.results or []
        requested_limit = self.query.limit or DEFAULT_LIMIT
        columns = (
            [column.alias if isinstance(column, ast.Alias) else column for column in query.select]
            if isinstance(query, ast.SelectQuery)
            else []
        )

        # Check if there are more results
        has_more = len(results) > requested_limit

        # Trim results to the requested limit if we got extra
        if has_more:
            results = results[:requested_limit]

        return MarketingAnalyticsTableQueryResponse(
            results=results,
            columns=columns,
            types=response.types,
            hogql=response.hogql,
            timings=response.timings,
            modifiers=self.modifiers,
            hasMore=has_more,
            limit=requested_limit,
            offset=self.query.offset or 0,
        )

    def _get_filtered_select_columns(self, query: ast.SelectQuery) -> list[ast.Expr]:
        """Extract and filter select columns based on self.query.select"""
        if self.query.select:
            # Create a mapping of column names to their AST expressions
            column_mapping: dict[str, ast.Expr] = {}
            for col in query.select:
                if isinstance(col, ast.Alias):
                    column_mapping[col.alias] = col
                else:
                    column_mapping[str(col)] = col

            # Filter to only include requested columns
            filtered_select: list[ast.Expr] = []
            for requested_col in self.query.select:
                if requested_col in column_mapping:
                    filtered_select.append(column_mapping[requested_col])
            return filtered_select
        else:
            # If no specific columns requested, use all columns
            return query.select if query.select else []

    def _get_column_names_for_order_by(self, select_columns: list[ast.Expr]) -> list[str]:
        """Extract column names from AST expressions for order by"""
        return [col.alias if isinstance(col, ast.Alias) else str(col) for col in select_columns]

    def _build_compare_join(
        self, current_period_query: ast.SelectQuery, previous_period_query: ast.SelectQuery
    ) -> ast.JoinExpr:
        """Build the join expression for comparing current and previous periods"""
        return ast.JoinExpr(
            table=current_period_query,
            alias="current_period",
            next_join=ast.JoinExpr(
                table=previous_period_query,
                alias="previous_period",
                join_type="LEFT JOIN",
                constraint=ast.JoinConstraint(
                    expr=ast.And(
                        exprs=[
                            ast.CompareOperation(
                                left=ast.Field(chain=["current_period", "Campaign"]),
                                op=ast.CompareOperationOp.Eq,
                                right=ast.Field(chain=["previous_period", "Campaign"]),
                            ),
                            ast.CompareOperation(
                                left=ast.Field(chain=["current_period", "Source"]),
                                op=ast.CompareOperationOp.Eq,
                                right=ast.Field(chain=["previous_period", "Source"]),
                            ),
                        ]
                    ),
                    constraint_type="ON",
                ),
            ),
        )

    def _build_paginated_query(
        self, select_columns: list[ast.Expr], select_from: ast.JoinExpr | None, ctes=None
    ) -> ast.SelectQuery:
        """Build a paginated SelectQuery with common logic"""
        # Extract column names for order by
        select_column_names = self._get_column_names_for_order_by(select_columns)
        order_by_exprs = self._build_order_by_exprs(select_column_names)

        # Build LIMIT and OFFSET
        limit = self.query.limit or DEFAULT_LIMIT
        offset = self.query.offset or 0
        actual_limit = limit + PAGINATION_EXTRA  # Request one extra for pagination

        return ast.SelectQuery(
            select=select_columns,
            select_from=select_from,
            ctes=ctes,
            order_by=order_by_exprs,
            limit=ast.Constant(value=actual_limit),
            offset=ast.Constant(value=offset),
        )

    def calculate_without_compare(self) -> ast.SelectQuery:
        """Execute the query and return results with pagination support"""
        query = self.to_query()
        filtered_select = self._get_filtered_select_columns(query)
        return self._build_paginated_query(filtered_select, query.select_from, query.ctes)

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

    def calculate_with_compare(self) -> ast.SelectQuery:
        """Execute the query and return results with pagination support"""
        # For compare queries, we need to create a new query runner for the previous period
        from copy import deepcopy

        previous_query = deepcopy(self.query)
        previous_date_range = self._create_previous_period_date_range()
        previous_query.dateRange = DateRange(
            date_from=previous_date_range.date_from().isoformat(),
            date_to=previous_date_range.date_to().isoformat(),
        )

        # Create a new runner for the previous period
        previous_runner = MarketingAnalyticsTableQueryRunner(
            query=previous_query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        previous_period_query = previous_runner.to_query()
        current_period_query = self.to_query()

        # Create the join manually with proper AST structure
        join_expr = self._build_compare_join(current_period_query, previous_period_query)

        # Get column names for the compare query
        select_columns = self._get_filtered_select_columns(current_period_query)

        # Create tuple columns for comparison
        tuple_columns: list[ast.Expr] = [
            ast.Alias(
                alias=col.alias if isinstance(col, ast.Alias) else str(col),
                expr=ast.Call(
                    name="tuple",
                    args=[
                        ast.Field(chain=["current_period", col.alias if isinstance(col, ast.Alias) else str(col)]),
                        ast.Field(chain=["previous_period", col.alias if isinstance(col, ast.Alias) else str(col)]),
                    ],
                ),
            )
            for col in select_columns
        ]

        return self._build_paginated_query(tuple_columns, join_expr)

    def _build_campaign_cost_select(self, union_query_string: str) -> ast.SelectQuery:
        """Build the campaign_costs CTE SELECT query"""
        # Build SELECT columns for the CTE
        select_columns: list[ast.Expr] = [
            ast.Field(chain=[MarketingSourceAdapter.campaign_name_field]),
            ast.Field(chain=[MarketingSourceAdapter.source_name_field]),
            ast.Alias(
                alias=TOTAL_COST_FIELD,
                expr=ast.Call(name="sum", args=[ast.Field(chain=[MarketingSourceAdapter.cost_field])]),
            ),
            ast.Alias(
                alias=TOTAL_CLICKS_FIELD,
                expr=ast.Call(name="sum", args=[ast.Field(chain=[MarketingSourceAdapter.clicks_field])]),
            ),
            ast.Alias(
                alias=TOTAL_IMPRESSIONS_FIELD,
                expr=ast.Call(name="sum", args=[ast.Field(chain=[MarketingSourceAdapter.impressions_field])]),
            ),
        ]

        # Parse the union query as a subquery and wrap it in a JoinExpr
        union_subquery = parse_select(union_query_string)
        union_join_expr = ast.JoinExpr(table=union_subquery)

        # Build GROUP BY
        group_by_exprs: list[ast.Expr] = [
            ast.Field(chain=[MarketingSourceAdapter.campaign_name_field]),
            ast.Field(chain=[MarketingSourceAdapter.source_name_field]),
        ]

        # Build the CTE SELECT query
        return ast.SelectQuery(select=select_columns, select_from=union_join_expr, group_by=group_by_exprs)

    def _build_select_columns_mapping(self, processors: list[ConversionGoalProcessor]) -> dict[str, ast.Expr]:
        all_columns: dict[str, ast.Expr] = {str(k): v for k, v in BASE_COLUMN_MAPPING.items()}
        for processor in processors:
            conversion_goal_expr, cost_per_goal_expr = processor.generate_select_columns()
            all_columns.update(
                {conversion_goal_expr.alias: conversion_goal_expr, cost_per_goal_expr.alias: cost_per_goal_expr}
            )

        return all_columns

    def _build_select_query(self, processors: list) -> ast.SelectQuery:
        """Build the complete SELECT query with base columns and conversion goal columns"""
        # Get conversion goal components (processors already created and passed in)
        conversion_columns_mapping = self._build_select_columns_mapping(processors)
        if processors:
            conversion_joins = self._generate_conversion_goal_joins_from_processors(processors)
        else:
            conversion_joins = []

        # Create the FROM clause with base table
        from_clause = ast.JoinExpr(table=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME]))

        # Add conversion goal joins
        if conversion_joins:
            from_clause = self._append_joins(from_clause, conversion_joins)

        return ast.SelectQuery(
            select=list(conversion_columns_mapping.values()),
            select_from=from_clause,
        )

    def _append_joins(self, initial_join: ast.JoinExpr, joins: list[ast.JoinExpr]) -> ast.JoinExpr:
        """Recursively append joins to the initial join by using the next_join field"""
        base_join = initial_join
        for current_join in joins:
            while base_join.next_join is not None:
                base_join = base_join.next_join
            base_join.next_join = current_join
        return initial_join

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

    def _build_order_by_exprs(self, select_columns: list[str]) -> list[ast.OrderExpr]:
        """Build ORDER BY expressions from query orderBy with proper null handling"""

        order_by_exprs: list[ast.OrderExpr] = []

        if hasattr(self.query, "orderBy") and self.query.orderBy and len(self.query.orderBy) > 0:
            for order_expr_str in self.query.orderBy:
                column_name, order_by = order_expr_str
                if column_name in select_columns:
                    order_by_exprs.append(
                        ast.OrderExpr(
                            expr=ast.Field(chain=[column_name]), order=cast(Literal["ASC", "DESC"], str(order_by))
                        )
                    )
        else:
            if MarketingAnalyticsBaseColumns.TOTAL_COST.value in select_columns:
                # Build default order by: Total Cost DESC
                default_field = ast.Field(chain=[MarketingAnalyticsBaseColumns.TOTAL_COST.value])
                order_by_exprs.append(ast.OrderExpr(expr=default_field, order="DESC"))

        return order_by_exprs

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
                processor = ConversionGoalProcessor(goal=conversion_goal, index=index, team=self.team)
                processors.append(processor)
        return processors

    def _generate_conversion_goal_joins_from_processors(self, processors: list) -> list[ast.JoinExpr]:
        """Generate JOIN clauses for conversion goals"""
        if not processors:
            return []

        joins = []
        for processor in processors:
            # Let the processor generate its own JOIN clause
            join_clause = processor.generate_join_clause()
            joins.append(join_clause)

        return joins

    def _generate_conversion_goal_selects_from_processors(
        self, processors: list[ConversionGoalProcessor]
    ) -> list[ast.Expr]:
        """Generate SELECT columns for conversion goals"""
        if not processors:
            return []

        all_selects: list[ast.Expr] = []
        for processor in processors:
            # Let the processor generate its own SELECT columns
            select_columns = processor.generate_select_columns()
            all_selects.extend(select_columns)

        return all_selects

    def _get_team_conversion_goals(self) -> list[ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3]:
        """Get conversion goals from team marketing analytics config and convert to proper objects"""
        conversion_goals = convert_team_conversion_goals_to_objects(
            self.team.marketing_analytics_config.conversion_goals, self.team.pk
        )

        if self.query.draftConversionGoal:
            conversion_goals = [self.query.draftConversionGoal, *conversion_goals]

        return conversion_goals

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
