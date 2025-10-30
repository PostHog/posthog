from copy import deepcopy
from typing import Literal, Optional, cast

import structlog

from posthog.schema import (
    CachedMarketingAnalyticsTableQueryResponse,
    DateRange,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsItem,
    MarketingAnalyticsTableQuery,
    MarketingAnalyticsTableQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator

from products.marketing_analytics.backend.hogql_queries.marketing_analytics_config import MarketingAnalyticsConfig

from .constants import (
    BASE_COLUMN_MAPPING,
    DEFAULT_LIMIT,
    PAGINATION_EXTRA,
    UNIFIED_CONVERSION_GOALS_CTE_ALIAS,
    to_marketing_analytics_data,
)
from .conversion_goals_aggregator import ConversionGoalsAggregator
from .marketing_analytics_base_query_runner import MarketingAnalyticsBaseQueryRunner

logger = structlog.get_logger(__name__)


class MarketingAnalyticsTableQueryRunner(MarketingAnalyticsBaseQueryRunner[MarketingAnalyticsTableQueryResponse]):
    query: MarketingAnalyticsTableQuery
    cached_response: CachedMarketingAnalyticsTableQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context, limit=self.query.limit, offset=self.query.offset
        )
        # Initialize configuration with team-specific settings
        self.config = MarketingAnalyticsConfig.from_team(self.team)

    # Implementation of abstract methods from base class

    def _build_main_select_query(
        self, conversion_aggregator: Optional[ConversionGoalsAggregator] = None
    ) -> ast.SelectQuery:
        """Build the main SELECT query for table queries with detailed rows"""
        return self._build_select_query(conversion_aggregator)

    def _calculate(self) -> MarketingAnalyticsTableQueryResponse:
        """Execute the query and return results with pagination support"""

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

        has_comparison = bool(self.query.compareFilter is not None and self.query.compareFilter.compare)

        # Transform results to MarketingAnalyticsItem objects
        results = self._transform_results_to_marketing_analytics_items(results, columns, has_comparison)

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

    def _build_flexible_source_join_condition(self) -> ast.Expr:
        """
        Build source join condition.
        Source normalization happens in conversion_goal_processor._normalize_source_field,
        so we can use simple equality here.
        """
        return ast.CompareOperation(
            left=ast.Field(chain=self.config.get_campaign_cost_field_chain(self.config.source_field)),
            op=ast.CompareOperationOp.Eq,
            right=ast.Field(chain=self.config.get_unified_conversion_field_chain(self.config.source_field)),
        )

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
                                left=ast.Field(chain=["current_period", MarketingAnalyticsBaseColumns.CAMPAIGN.value]),
                                op=ast.CompareOperationOp.Eq,
                                right=ast.Field(
                                    chain=["previous_period", MarketingAnalyticsBaseColumns.CAMPAIGN.value]
                                ),
                            ),
                            ast.CompareOperation(
                                left=ast.Field(chain=["current_period", MarketingAnalyticsBaseColumns.SOURCE.value]),
                                op=ast.CompareOperationOp.Eq,
                                right=ast.Field(chain=["previous_period", MarketingAnalyticsBaseColumns.SOURCE.value]),
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

    def calculate_with_compare(self) -> ast.SelectQuery:
        """Execute the query and return results with pagination support"""
        # For compare queries, we need to create a new query runner for the previous period

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

    def _build_select_columns_mapping(
        self, conversion_aggregator: Optional[ConversionGoalsAggregator] = None
    ) -> dict[str, ast.Expr]:
        all_columns: dict[str, ast.Expr] = {str(k): v for k, v in BASE_COLUMN_MAPPING.items()}

        # Add conversion goal columns using the aggregator
        if conversion_aggregator:
            # For FULL OUTER JOIN: use COALESCE to show conversion goal UTM values when campaign costs are empty
            if self.query.includeAllConversions:
                coalesce_columns = conversion_aggregator.get_coalesce_fallback_columns()
                all_columns.update(coalesce_columns)

            # Add conversion goal columns
            conversion_columns = conversion_aggregator.get_conversion_goal_columns()
            all_columns.update(conversion_columns)

        return all_columns

    def _build_select_query(self, conversion_aggregator: Optional[ConversionGoalsAggregator] = None) -> ast.SelectQuery:
        """Build the complete SELECT query with base columns and conversion goal columns"""
        # Get conversion goal components
        conversion_columns_mapping = self._build_select_columns_mapping(conversion_aggregator)

        # Create the FROM clause with base table
        from_clause = ast.JoinExpr(table=ast.Field(chain=[self.config.campaign_costs_cte_name]))

        # Add single unified conversion goals join if we have conversion goals
        if conversion_aggregator:
            join_type = "FULL OUTER JOIN" if self.query.includeAllConversions else "LEFT JOIN"
            unified_join = ast.JoinExpr(
                join_type=join_type,
                table=ast.Field(chain=[UNIFIED_CONVERSION_GOALS_CTE_ALIAS]),
                alias=self.config.unified_conversion_goals_cte_alias,
                constraint=ast.JoinConstraint(
                    expr=ast.And(
                        exprs=[
                            ast.CompareOperation(
                                left=ast.Field(
                                    chain=self.config.get_campaign_cost_field_chain(self.config.campaign_field)
                                ),
                                op=ast.CompareOperationOp.Eq,
                                right=ast.Field(
                                    chain=self.config.get_unified_conversion_field_chain(self.config.campaign_field)
                                ),
                            ),
                            self._build_flexible_source_join_condition(),
                        ]
                    ),
                    constraint_type="ON",
                ),
            )
            from_clause.next_join = unified_join

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
            if MarketingAnalyticsBaseColumns.COST.value in select_columns:
                # Build default order by: Total Cost DESC
                default_field = ast.Field(chain=[MarketingAnalyticsBaseColumns.COST.value])
                order_by_exprs.append(ast.OrderExpr(expr=default_field, order="DESC"))

        return order_by_exprs

    def _transform_results_to_marketing_analytics_items(
        self, results: list, columns: list, has_comparison: bool
    ) -> list:
        """Transform raw query results to MarketingAnalyticsItem objects."""
        logger.debug(
            "transforming_results_to_marketing_analytics",
            row_count=len(results),
            column_count=len(columns),
            has_comparison=has_comparison,
        )

        transformed_results = []
        for row in results:
            transformed_row = []
            for i, column_name in enumerate(columns):
                transformed_item = self._transform_cell_to_marketing_analytics_item(row, i, column_name, has_comparison)
                transformed_row.append(transformed_item)
            transformed_results.append(transformed_row)
        return transformed_results

    def _transform_cell_to_marketing_analytics_item(
        self, row: list, column_index: int, column_name: str, has_comparison: bool
    ) -> MarketingAnalyticsItem:
        """Transform a single cell value to a MarketingAnalyticsItem object."""
        if column_index < len(row):
            cell_value = row[column_index]

            if has_comparison and isinstance(cell_value, list | tuple) and len(cell_value) >= 2:
                # This is a tuple from compare query: (current, previous)
                current_value, previous_value = cell_value[0], cell_value[1]
                return to_marketing_analytics_data(
                    key=str(column_name),
                    value=current_value,
                    previous=previous_value,
                    has_comparison=has_comparison,
                )
            else:
                # Single value, create object with no previous data
                return to_marketing_analytics_data(
                    key=str(column_name),
                    value=cell_value,
                    previous=None,
                    has_comparison=has_comparison,
                )
        else:
            # Missing column data
            return to_marketing_analytics_data(
                key=str(column_name),
                value=None,
                previous=None,
                has_comparison=has_comparison,
            )
