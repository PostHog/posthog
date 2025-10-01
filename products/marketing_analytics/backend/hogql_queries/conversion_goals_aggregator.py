from posthog.hogql import ast

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from .conversion_goal_processor import ConversionGoalProcessor
from .marketing_analytics_config import MarketingAnalyticsConfig


class ConversionGoalsAggregator:
    """
    A dedicated query runner that creates a single unified table of all conversion goals
    grouped by campaign and source
    """

    def __init__(self, processors: list[ConversionGoalProcessor], config: MarketingAnalyticsConfig):
        self.processors = processors
        self.config = config

    def generate_unified_cte(self, date_range: QueryDateRange, additional_conditions_getter) -> ast.CTE:
        """Generate a single CTE that contains all conversion goals aggregated by campaign/source"""
        if not self.processors:
            raise ValueError("Cannot create unified CTE without conversion goal processors")

        # Step 1: Generate individual conversion goal queries
        conversion_subqueries = []

        for processor in self.processors:
            # Build additional conditions for this processor
            date_field = processor.get_date_field()
            additional_conditions = additional_conditions_getter(
                date_range=date_range,
                include_date_range=True,
                date_field=date_field,
                use_date_not_datetime=True,
            )

            # Generate the base conversion goal query
            base_query = processor.generate_cte_query(additional_conditions)

            # Transform the query to include a column for this specific conversion goal
            # and zero columns for all other conversion goals
            enhanced_select = [
                # Keep campaign and source
                base_query.select[0],  # campaign
                base_query.select[1],  # source
            ]

            # Add columns for all conversion goals (this one gets the actual value, others get 0)
            for p in self.processors:
                if p.index == processor.index:
                    # This is the current processor - use the actual conversion value
                    # Extract the expression from the alias to avoid double aliasing
                    conversion_expr = base_query.select[2]
                    if isinstance(conversion_expr, ast.Alias):
                        conversion_expr = conversion_expr.expr
                    enhanced_select.append(
                        ast.Alias(
                            alias=self.config.get_conversion_goal_column_name(p.index),
                            expr=conversion_expr,
                        )
                    )
                else:
                    # This is a different processor - add zero column
                    enhanced_select.append(
                        ast.Alias(
                            alias=self.config.get_conversion_goal_column_name(p.index), expr=ast.Constant(value=0)
                        )
                    )

            enhanced_query = ast.SelectQuery(
                select=enhanced_select,
                select_from=base_query.select_from,
                where=base_query.where,
                group_by=base_query.group_by,
                having=base_query.having,
                array_join_op=base_query.array_join_op,
                array_join_list=base_query.array_join_list,
            )

            conversion_subqueries.append(enhanced_query)

        # Step 2: UNION ALL the individual queries
        if len(conversion_subqueries) == 1:
            union_query: ast.SelectQuery | ast.SelectSetQuery = conversion_subqueries[0]
        else:
            union_query = ast.SelectSetQuery.create_from_queries(conversion_subqueries, "UNION ALL")

        # Step 3: Create final aggregation query that sums all conversion goals by campaign/source
        final_select: list[ast.Expr] = [ast.Field(chain=[field]) for field in self.config.group_by_fields]

        # Add each conversion goal as a summed column
        for processor in self.processors:
            final_select.append(
                ast.Alias(
                    alias=self.config.get_conversion_goal_column_name(processor.index),
                    expr=ast.Call(
                        name="sum",
                        args=[ast.Field(chain=[self.config.get_conversion_goal_column_name(processor.index)])],
                    ),
                )
            )

        final_query = ast.SelectQuery(
            select=final_select,
            select_from=ast.JoinExpr(table=union_query),
            group_by=[ast.Field(chain=[field]) for field in self.config.group_by_fields],
        )

        return ast.CTE(name="unified_conversion_goals", expr=final_query, cte_type="subquery")

    def get_conversion_goal_columns(self) -> dict[str, ast.Alias]:
        """Get the column mappings for accessing conversion goals from the unified CTE"""
        columns = {}

        for processor in self.processors:
            goal_name = processor.goal.conversion_goal_name

            # Conversion goal column
            conversion_goal_alias = ast.Alias(
                alias=goal_name,
                expr=ast.Field(
                    chain=self.config.get_unified_conversion_field_chain(
                        self.config.get_conversion_goal_column_name(processor.index)
                    )
                ),
            )

            # Cost per conversion column
            cost_per_goal_alias = ast.Alias(
                alias=f"{self.config.cost_per_prefix} {goal_name}",
                expr=ast.Call(
                    name="round",
                    args=[
                        ast.ArithmeticOperation(
                            left=ast.Field(
                                chain=self.config.get_campaign_cost_field_chain(self.config.total_cost_field)
                            ),
                            op=ast.ArithmeticOperationOp.Div,
                            right=ast.Call(
                                name="nullif",
                                args=[
                                    ast.Field(
                                        chain=self.config.get_unified_conversion_field_chain(
                                            self.config.get_conversion_goal_column_name(processor.index)
                                        )
                                    ),
                                    ast.Constant(value=0),
                                ],
                            ),
                        ),
                        ast.Constant(value=2),
                    ],
                ),
            )

            columns[goal_name] = conversion_goal_alias
            columns[f"{self.config.cost_per_prefix} {goal_name}"] = cost_per_goal_alias

        return columns

    def get_coalesce_fallback_columns(self) -> dict[str, ast.Expr]:
        """Get COALESCE columns that fall back to unified conversion goals for campaign/source"""
        # Use the config group_by_fields to build COALESCE expressions
        campaign_field, source_field = self.config.group_by_fields

        campaign_args = [
            ast.Call(
                name="nullif",
                args=[
                    ast.Field(chain=self.config.get_campaign_cost_field_chain(campaign_field)),
                    ast.Constant(value=""),
                ],
            ),
            ast.Call(
                name="nullif",
                args=[
                    ast.Field(chain=self.config.get_unified_conversion_field_chain(campaign_field)),
                    ast.Constant(value=""),
                ],
            ),
            ast.Constant(value=self.config.organic_campaign),
        ]

        source_args = [
            ast.Call(
                name="nullif",
                args=[
                    ast.Field(chain=self.config.get_campaign_cost_field_chain(source_field)),
                    ast.Constant(value=""),
                ],
            ),
            ast.Call(
                name="nullif",
                args=[
                    ast.Field(chain=self.config.get_unified_conversion_field_chain(source_field)),
                    ast.Constant(value=""),
                ],
            ),
            ast.Constant(value=self.config.organic_source),
        ]

        return {
            self.config.campaign_column_alias: ast.Alias(
                alias=self.config.campaign_column_alias, expr=ast.Call(name="coalesce", args=campaign_args)
            ),
            self.config.source_column_alias: ast.Alias(
                alias=self.config.source_column_alias, expr=ast.Call(name="coalesce", args=source_args)
            ),
        }
