from copy import deepcopy
from typing import Literal, Optional, cast

import structlog

from posthog.schema import (
    CachedNonIntegratedConversionsTableQueryResponse,
    DateRange,
    MarketingAnalyticsItem,
    NonIntegratedConversionsColumnsSchemaNames,
    NonIntegratedConversionsTableQuery,
    NonIntegratedConversionsTableQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator

from products.marketing_analytics.backend.hogql_queries.marketing_analytics_config import MarketingAnalyticsConfig

from .constants import DEFAULT_LIMIT, PAGINATION_EXTRA, UNIFIED_CONVERSION_GOALS_CTE_ALIAS, to_marketing_analytics_data
from .conversion_goals_aggregator import ConversionGoalsAggregator
from .marketing_analytics_base_query_runner import MarketingAnalyticsBaseQueryRunner

logger = structlog.get_logger(__name__)


class NonIntegratedConversionsTableQueryRunner(
    MarketingAnalyticsBaseQueryRunner[NonIntegratedConversionsTableQueryResponse]
):
    """
    Query runner for non-integrated conversions.
    Shows conversion data that does NOT match any campaign costs from integrations.
    This helps users identify conversions with UTM parameters that aren't mapped to any integration.
    """

    query: NonIntegratedConversionsTableQuery
    cached_response: CachedNonIntegratedConversionsTableQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context, limit=self.query.limit, offset=self.query.offset
        )
        self.config = MarketingAnalyticsConfig.from_team(self.team)

    def _get_marketing_source_adapters(self, date_range):
        """
        Override to get ALL marketing source adapters without integration filter.
        NonIntegratedConversionsTableQuery doesn't have integrationFilter attribute,
        and we want to compare against ALL integrations to find non-matching conversions.
        """
        from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory

        try:
            factory: MarketingSourceFactory = self._factory(date_range=date_range)
            adapters = factory.create_adapters()
            valid_adapters = factory.get_valid_adapters(adapters)
            # Don't apply integration filter - we want ALL adapters
            return valid_adapters
        except Exception as e:
            logger.exception("Error getting marketing source adapters for non-integrated query", error=str(e))
            return []

    def _build_main_select_query(
        self, conversion_aggregator: Optional[ConversionGoalsAggregator] = None
    ) -> ast.SelectQuery:
        """Build the main SELECT query for non-integrated conversions"""
        return self._build_select_query(conversion_aggregator)

    def _calculate(self) -> NonIntegratedConversionsTableQueryResponse:
        """Execute the query and return results with pagination support."""
        is_compare = self.query.compareFilter is not None and self.query.compareFilter.compare

        if is_compare:
            query = self.calculate_with_compare()
        else:
            query = self.calculate_without_compare()

        response = execute_hogql_query(
            query_type="non_integrated_conversions_table_query",
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

        return NonIntegratedConversionsTableQueryResponse(
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
            column_mapping: dict[str, ast.Expr] = {}
            for col in query.select:
                if isinstance(col, ast.Alias):
                    column_mapping[col.alias] = col
                else:
                    column_mapping[str(col)] = col

            filtered_select: list[ast.Expr] = []
            for requested_col in self.query.select:
                if requested_col in column_mapping:
                    filtered_select.append(column_mapping[requested_col])
            return filtered_select
        else:
            return query.select if query.select else []

    def _get_column_names_for_order_by(self, select_columns: list[ast.Expr]) -> list[str]:
        """Extract column names from AST expressions for order by"""
        return [col.alias if isinstance(col, ast.Alias) else str(col) for col in select_columns]

    def _build_paginated_query(
        self,
        select_columns: list[ast.Expr],
        select_from: ast.JoinExpr | None,
        ctes=None,
        where: ast.Expr | None = None,
    ) -> ast.SelectQuery:
        """Build a paginated SelectQuery with common logic"""
        select_column_names = self._get_column_names_for_order_by(select_columns)
        order_by_exprs = self._build_order_by_exprs(select_column_names)

        limit = self.query.limit or DEFAULT_LIMIT
        offset = self.query.offset or 0
        actual_limit = limit + PAGINATION_EXTRA

        return ast.SelectQuery(
            select=select_columns,
            select_from=select_from,
            ctes=ctes,
            where=where,
            order_by=order_by_exprs,
            limit=ast.Constant(value=actual_limit),
            offset=ast.Constant(value=offset),
        )

    def calculate_without_compare(self) -> ast.SelectQuery:
        """Build the final query with pagination for non-comparison mode."""
        query = self.to_query()
        filtered_select = self._get_filtered_select_columns(query)

        select_column_names = self._get_column_names_for_order_by(filtered_select)
        order_by_exprs = self._build_order_by_exprs(select_column_names)
        limit = self.query.limit or DEFAULT_LIMIT
        offset = self.query.offset or 0
        actual_limit = limit + PAGINATION_EXTRA

        # Modify the query in-place to preserve CTEs, JOINs, and WHERE clause
        query.select = filtered_select
        query.order_by = order_by_exprs
        query.limit = ast.Constant(value=actual_limit)
        query.offset = ast.Constant(value=offset)

        return query

    def calculate_with_compare(self) -> ast.SelectQuery:
        """Build the final query with comparison to previous period."""
        previous_query = deepcopy(self.query)
        previous_date_range = self._create_previous_period_date_range()
        previous_query.dateRange = DateRange(
            date_from=previous_date_range.date_from().isoformat(),
            date_to=previous_date_range.date_to().isoformat(),
        )

        previous_runner = NonIntegratedConversionsTableQueryRunner(
            query=previous_query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        previous_period_query = previous_runner.to_query()
        current_period_query = self.to_query()

        join_expr = self._build_compare_join(current_period_query, previous_period_query)
        select_columns = self._get_filtered_select_columns(current_period_query)

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
                                left=ast.Field(
                                    chain=["current_period", NonIntegratedConversionsColumnsSchemaNames.CAMPAIGN.value]
                                ),
                                op=ast.CompareOperationOp.Eq,
                                right=ast.Field(
                                    chain=["previous_period", NonIntegratedConversionsColumnsSchemaNames.CAMPAIGN.value]
                                ),
                            ),
                            ast.CompareOperation(
                                left=ast.Field(
                                    chain=["current_period", NonIntegratedConversionsColumnsSchemaNames.SOURCE.value]
                                ),
                                op=ast.CompareOperationOp.Eq,
                                right=ast.Field(
                                    chain=["previous_period", NonIntegratedConversionsColumnsSchemaNames.SOURCE.value]
                                ),
                            ),
                        ]
                    ),
                    constraint_type="ON",
                ),
            ),
        )

    def _build_select_query(self, conversion_aggregator: Optional[ConversionGoalsAggregator] = None) -> ast.SelectQuery:
        """
        Build the SELECT query for non-integrated conversions.
        This queries only from the unified conversion goals CTE (no campaign costs join).
        """
        if not conversion_aggregator:
            # If no conversion goals, return empty result
            return ast.SelectQuery(
                select=[
                    ast.Alias(
                        alias=NonIntegratedConversionsColumnsSchemaNames.SOURCE.value, expr=ast.Constant(value="")
                    ),
                    ast.Alias(
                        alias=NonIntegratedConversionsColumnsSchemaNames.CAMPAIGN.value, expr=ast.Constant(value="")
                    ),
                ],
                where=ast.Constant(value=False),  # Always return empty
            )

        # Build select columns: Source, Campaign, and conversion goal columns
        select_columns: list[ast.Expr] = [
            ast.Alias(
                alias=NonIntegratedConversionsColumnsSchemaNames.SOURCE.value,
                expr=ast.Field(chain=[UNIFIED_CONVERSION_GOALS_CTE_ALIAS, self.config.source_field]),
            ),
            ast.Alias(
                alias=NonIntegratedConversionsColumnsSchemaNames.CAMPAIGN.value,
                expr=ast.Field(chain=[UNIFIED_CONVERSION_GOALS_CTE_ALIAS, self.config.campaign_field]),
            ),
        ]

        # Add conversion goal columns (without cost per, since non-integrated conversions have no cost data)
        conversion_columns = conversion_aggregator.get_conversion_goal_columns(include_cost_per=False)
        select_columns.extend(conversion_columns.values())

        # Select from the unified conversion goals CTE
        # Don't use an alias that matches the CTE name to avoid issues with CTE resolution
        from_clause = ast.JoinExpr(
            table=ast.Field(chain=[UNIFIED_CONVERSION_GOALS_CTE_ALIAS]),
        )

        # Add LEFT JOIN with campaign_costs and filter for non-matching rows
        # This gives us only conversions that don't have matching campaign data
        campaign_costs_alias = "cc"
        from_clause.next_join = ast.JoinExpr(
            join_type="LEFT JOIN",
            table=ast.Field(chain=[self.config.campaign_costs_cte_name]),
            alias=campaign_costs_alias,
            constraint=ast.JoinConstraint(
                expr=ast.And(
                    exprs=[
                        # Join on match_key (ClickHouse doesn't support OR in JOIN ON conditions)
                        # match_key is set by adapters based on team preferences (campaign_name or campaign_id)
                        ast.CompareOperation(
                            left=ast.Field(chain=[UNIFIED_CONVERSION_GOALS_CTE_ALIAS, self.config.match_key_field]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Field(chain=[campaign_costs_alias, self.config.match_key_field]),
                        ),
                        ast.CompareOperation(
                            left=ast.Field(chain=[UNIFIED_CONVERSION_GOALS_CTE_ALIAS, self.config.source_field]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Field(chain=[campaign_costs_alias, self.config.source_field]),
                        ),
                    ]
                ),
                constraint_type="ON",
            ),
        )

        # WHERE clause: only rows where campaign_costs has no match (IS NULL)
        where_clause = ast.CompareOperation(
            left=ast.Field(chain=[campaign_costs_alias, self.config.campaign_field]),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value=None),
        )

        return ast.SelectQuery(
            select=select_columns,
            select_from=from_clause,
            where=where_clause,
        )

    def _build_order_by_exprs(self, select_columns: list[str]) -> list[ast.OrderExpr]:
        """Build ORDER BY expressions from query orderBy"""
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
            # Default: order by first conversion goal column if exists, otherwise by Campaign
            if len(select_columns) > 2:
                # Has conversion goal columns - order by first one DESC
                order_by_exprs.append(ast.OrderExpr(expr=ast.Field(chain=[select_columns[2]]), order="DESC"))
            elif NonIntegratedConversionsColumnsSchemaNames.CAMPAIGN.value in select_columns:
                order_by_exprs.append(
                    ast.OrderExpr(
                        expr=ast.Field(chain=[NonIntegratedConversionsColumnsSchemaNames.CAMPAIGN.value]), order="ASC"
                    )
                )

        return order_by_exprs

    def _transform_results_to_marketing_analytics_items(
        self, results: list, columns: list, has_comparison: bool
    ) -> list:
        """Transform raw query results to MarketingAnalyticsItem objects."""
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
                current_value, previous_value = cell_value[0], cell_value[1]
                return to_marketing_analytics_data(
                    key=str(column_name),
                    value=current_value,
                    previous=previous_value,
                    has_comparison=has_comparison,
                )
            else:
                return to_marketing_analytics_data(
                    key=str(column_name),
                    value=cell_value,
                    previous=None,
                    has_comparison=has_comparison,
                )
        else:
            return to_marketing_analytics_data(
                key=str(column_name),
                value=None,
                previous=None,
                has_comparison=has_comparison,
            )
