from copy import deepcopy
from typing import Optional

from posthog.schema import (
    CachedMarketingAnalyticsAggregatedQueryResponse,
    DateRange,
    MarketingAnalyticsAggregatedQuery,
    MarketingAnalyticsAggregatedQueryResponse,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsHelperForColumnNames,
    MarketingAnalyticsItem,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from .constants import BASE_COLUMN_MAPPING, UNIFIED_CONVERSION_GOALS_CTE_ALIAS, to_marketing_analytics_data
from .conversion_goals_aggregator import ConversionGoalsAggregator
from .marketing_analytics_base_query_runner import MarketingAnalyticsBaseQueryRunner


class MarketingAnalyticsAggregatedQueryRunner(
    MarketingAnalyticsBaseQueryRunner[MarketingAnalyticsAggregatedQueryResponse]
):
    """Query runner for aggregated marketing analytics data across all campaigns/sources."""

    query: MarketingAnalyticsAggregatedQuery
    cached_response: CachedMarketingAnalyticsAggregatedQueryResponse

    def _build_main_select_query(
        self, conversion_aggregator: Optional[ConversionGoalsAggregator] = None
    ) -> ast.SelectQuery:
        """Build the main SELECT query for aggregated totals."""
        conversion_columns_mapping = self._build_select_columns_mapping(conversion_aggregator)
        from_clause = ast.JoinExpr(table=ast.Field(chain=[self.config.campaign_costs_cte_name]))
        if conversion_aggregator:
            join_type = "LEFT JOIN"
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
                            ast.CompareOperation(
                                left=ast.Field(
                                    chain=self.config.get_campaign_cost_field_chain(self.config.source_field)
                                ),
                                op=ast.CompareOperationOp.Eq,
                                right=ast.Field(
                                    chain=self.config.get_unified_conversion_field_chain(self.config.source_field)
                                ),
                            ),
                        ]
                    ),
                    constraint_type="ON",
                ),
            )
            from_clause.next_join = unified_join

        # Convert all columns to aggregated versions
        summed_columns = self._build_basic_summed_columns(conversion_columns_mapping)

        return ast.SelectQuery(
            select=list(summed_columns.values()),
            select_from=from_clause,
        )

    def _build_select_columns_mapping(
        self, conversion_aggregator: Optional[ConversionGoalsAggregator] = None
    ) -> dict[str, ast.Expr]:
        """Build column mappings excluding Campaign and Source columns for aggregated queries"""
        # Start with base columns but exclude Campaign, Source and rate metrics
        all_columns: dict[str, ast.Expr] = {
            str(k): v
            for k, v in BASE_COLUMN_MAPPING.items()
            if k
            not in (
                MarketingAnalyticsBaseColumns.CAMPAIGN,
                MarketingAnalyticsBaseColumns.SOURCE,
                MarketingAnalyticsBaseColumns.CPC,
                MarketingAnalyticsBaseColumns.CTR,
            )
        }

        # Add conversion goal columns using the aggregator
        if conversion_aggregator:
            conversion_columns = conversion_aggregator.get_conversion_goal_columns()
            # We exclude the `Cost per` conversion goal columns from the mapping because we'll recalculate them later
            conversion_columns = {
                k: v
                for k, v in conversion_columns.items()
                if not k.startswith(MarketingAnalyticsHelperForColumnNames.COST_PER)
            }
            all_columns.update(conversion_columns)

        return all_columns

    def _build_basic_summed_columns(self, basic_summed_columns: dict[str, ast.Expr]) -> dict[str, ast.Expr]:
        """Convert columns to aggregated versions - wrap numeric columns in SUM(), skip rate metrics and cost per conversion"""
        summed_columns: dict[str, ast.Expr] = {}

        for column_name, column_expr in basic_summed_columns.items():
            # For all other columns, wrap in SUM()
            if isinstance(column_expr, ast.Alias):
                summed_columns[column_name] = ast.Alias(
                    alias=column_expr.alias, expr=ast.Call(name="sum", args=[column_expr.expr])
                )
            else:
                summed_columns[column_name] = ast.Call(name="sum", args=[column_expr])

        return summed_columns

    def _calculate(self) -> MarketingAnalyticsAggregatedQueryResponse:
        """Execute the query and return aggregated results"""

        query: ast.SelectQuery
        if self.query.compareFilter is not None and self.query.compareFilter.compare:
            query = self.calculate_with_compare()
        else:
            query = self.calculate_without_compare()

        response = execute_hogql_query(
            query_type="marketing_analytics_aggregated_query",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        results = response.results or []
        columns = (
            [column.alias if isinstance(column, ast.Alias) else column for column in query.select]
            if isinstance(query, ast.SelectQuery)
            else []
        )

        has_comparison = bool(self.query.compareFilter is not None and self.query.compareFilter.compare)

        # Transform results to dictionary of MarketingAnalyticsItem objects
        results_dict = self._transform_results_to_dict(results, columns, has_comparison)

        return MarketingAnalyticsAggregatedQueryResponse(
            results=results_dict,
            hogql=response.hogql,
            timings=response.timings,
            modifiers=self.modifiers,
        )

    def calculate_without_compare(self) -> ast.SelectQuery:
        """Execute the query without comparison - no pagination needed"""
        query = self.to_query()
        filtered_select = self._get_filtered_select_columns(query)

        # No pagination for aggregated queries - return the query as-is
        return ast.SelectQuery(
            select=filtered_select,
            select_from=query.select_from,
            ctes=query.ctes,
        )

    def calculate_with_compare(self) -> ast.SelectQuery:
        """Execute the query with comparison - adapted from table query runner"""

        previous_query = deepcopy(self.query)
        previous_date_range = self._create_previous_period_date_range()
        previous_query.dateRange = DateRange(
            date_from=previous_date_range.date_from().isoformat(),
            date_to=previous_date_range.date_to().isoformat(),
        )

        # Create a new runner for the previous period
        previous_runner = MarketingAnalyticsAggregatedQueryRunner(
            query=previous_query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        previous_period_query = previous_runner.to_query()
        current_period_query = self.to_query()

        join_expr = ast.JoinExpr(
            table=current_period_query,
            alias="current_period",
            next_join=ast.JoinExpr(
                table=previous_period_query,
                alias="previous_period",
                join_type="LEFT JOIN",
                constraint=ast.JoinConstraint(
                    expr=ast.Constant(value=1),  # Always join since there's only one row each
                    constraint_type="ON",
                ),
            ),
        )

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

        return ast.SelectQuery(
            select=tuple_columns,
            select_from=join_expr,
        )

    def _get_filtered_select_columns(self, query: ast.SelectQuery) -> list[ast.Expr]:
        """Extract and filter select columns - same as table query runner"""
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

    def _transform_results_to_dict(
        self, results: list, columns: list, has_comparison: bool
    ) -> dict[str, MarketingAnalyticsItem]:
        """Transform results to dictionary of MarketingAnalyticsItem objects"""
        results_dict = {}

        if results and len(results) > 0:
            row = results[0]  # Only one row for aggregated results
            for i, column_name in enumerate(columns):
                transformed_item = self._transform_cell_to_marketing_analytics_item(row, i, column_name, has_comparison)
                results_dict[column_name] = transformed_item

        # Recalculate rate metrics and cost per conversion metrics after summing
        self._add_rate_metrics(results_dict, has_comparison)
        self._add_cost_per_conversion_metrics(results_dict, has_comparison)

        return results_dict

    def _transform_cell_to_marketing_analytics_item(
        self, row: list, column_index: int, column_name: str, has_comparison: bool
    ) -> MarketingAnalyticsItem:
        """Transform a single cell value - same as table query runner"""
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

    def _add_rate_metrics(self, results_dict: dict, has_comparison: bool) -> None:
        """Add rate metrics (CPC, CTR) by recalculating from aggregated base values"""
        # Get base values from results
        total_cost_item = results_dict.get(MarketingAnalyticsBaseColumns.COST.value)
        total_clicks_item = results_dict.get(MarketingAnalyticsBaseColumns.CLICKS.value)
        total_impressions_item = results_dict.get(MarketingAnalyticsBaseColumns.IMPRESSIONS.value)

        # Calculate CPC (Cost Per Click)
        if total_cost_item and total_clicks_item:
            if has_comparison and total_cost_item.previous is not None and total_clicks_item.previous is not None:
                # Current period CPC
                current_cpc = self._calculate_rate(total_cost_item.value, total_clicks_item.value)
                # Previous period CPC
                previous_cpc = self._calculate_rate(total_cost_item.previous, total_clicks_item.previous)

                cpc_item = to_marketing_analytics_data(
                    key=MarketingAnalyticsBaseColumns.CPC.value,
                    value=current_cpc,
                    previous=previous_cpc,
                    has_comparison=has_comparison,
                )
            else:
                # No comparison data
                cpc_value = self._calculate_rate(total_cost_item.value, total_clicks_item.value)
                cpc_item = to_marketing_analytics_data(
                    key=MarketingAnalyticsBaseColumns.CPC.value,
                    value=cpc_value,
                    previous=None,
                    has_comparison=has_comparison,
                )
            results_dict[MarketingAnalyticsBaseColumns.CPC.value] = cpc_item

        # Calculate CTR (Click Through Rate)
        if total_clicks_item and total_impressions_item:
            if (
                has_comparison
                and total_clicks_item.previous is not None
                and total_impressions_item.previous is not None
            ):
                # Current period CTR (multiply by 100 for percentage)
                current_ctr = self._calculate_rate(
                    total_clicks_item.value, total_impressions_item.value, multiply_by_100=True
                )
                # Previous period CTR
                previous_ctr = self._calculate_rate(
                    total_clicks_item.previous, total_impressions_item.previous, multiply_by_100=True
                )

                ctr_item = to_marketing_analytics_data(
                    key=MarketingAnalyticsBaseColumns.CTR.value,
                    value=current_ctr,
                    previous=previous_ctr,
                    has_comparison=has_comparison,
                )
            else:
                # No comparison data
                ctr_value = self._calculate_rate(
                    total_clicks_item.value, total_impressions_item.value, multiply_by_100=True
                )
                ctr_item = to_marketing_analytics_data(
                    key=MarketingAnalyticsBaseColumns.CTR.value,
                    value=ctr_value,
                    previous=None,
                    has_comparison=has_comparison,
                )
            results_dict[MarketingAnalyticsBaseColumns.CTR.value] = ctr_item

    def _calculate_rate(self, numerator, denominator, multiply_by_100: bool = False) -> float | None:
        """Calculate a rate (numerator/denominator), handling division by zero"""
        if numerator is None or denominator is None or denominator == 0:
            return None

        rate = float(numerator) / float(denominator)
        if multiply_by_100:
            rate *= 100

        return round(rate, 2)

    def _add_cost_per_conversion_metrics(self, results_dict: dict, has_comparison: bool) -> None:
        """Add cost per conversion metrics by recalculating from aggregated totals"""
        # Get total cost from results
        total_cost_item = results_dict.get(MarketingAnalyticsBaseColumns.COST.value)
        if not total_cost_item:
            return

        # Find all conversion goal metrics and calculate cost per conversion for each
        conversion_goals = []
        base_metric_keys = {col.value for col in MarketingAnalyticsBaseColumns}
        for key in results_dict.keys():
            # Skip base metrics and cost per conversion metrics
            if key in base_metric_keys or key.startswith(MarketingAnalyticsHelperForColumnNames.COST_PER):
                continue
            conversion_goals.append(key)

        for goal_name in conversion_goals:
            conversion_item = results_dict.get(goal_name)
            if not conversion_item:
                continue

            # Calculate cost per conversion using the same prefix as the config
            cost_per_key = f"{MarketingAnalyticsHelperForColumnNames.COST_PER} {goal_name}"

            # Handle comparison data
            if has_comparison and conversion_item.previous is not None and total_cost_item.previous is not None:
                # Current period
                current_cost_per = self._calculate_cost_per_conversion(total_cost_item.value, conversion_item.value)
                # Previous period
                previous_cost_per = self._calculate_cost_per_conversion(
                    total_cost_item.previous, conversion_item.previous
                )

                cost_per_item = to_marketing_analytics_data(
                    key=cost_per_key,
                    value=current_cost_per,
                    previous=previous_cost_per,
                    has_comparison=has_comparison,
                )
            else:
                # No comparison data
                cost_per_value = self._calculate_cost_per_conversion(total_cost_item.value, conversion_item.value)

                cost_per_item = to_marketing_analytics_data(
                    key=cost_per_key,
                    value=cost_per_value,
                    previous=None,
                    has_comparison=has_comparison,
                )

            results_dict[cost_per_key] = cost_per_item

    def _calculate_cost_per_conversion(self, total_cost, total_conversions) -> float | None:
        """Calculate cost per conversion, handling division by zero"""
        if total_cost is None or total_conversions is None or total_conversions == 0:
            return None
        return round(float(total_cost) / float(total_conversions), 2)
