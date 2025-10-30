from posthog.hogql import ast

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.marketing_analytics.backend.hogql_queries.constants import UNIFIED_CONVERSION_GOALS_CTE_ALIAS

from .adapters.factory import MarketingSourceFactory
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
        # First, wrap the union in a subquery to materialize campaign/source fields
        subquery_alias = "conv"

        final_select: list[ast.Expr] = [
            ast.Field(chain=[self.config.campaign_field]),
            ast.Field(chain=[self.config.source_field]),
        ]

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
            select_from=ast.JoinExpr(table=union_query, alias=subquery_alias),
            group_by=[
                ast.Field(chain=[self.config.campaign_field]),
                ast.Field(chain=[self.config.source_field]),
            ],
        )

        # Now apply campaign name mappings by wrapping in another SELECT
        campaign_field_expr = ast.Field(chain=[self.config.campaign_field])
        source_field_expr = ast.Field(chain=[self.config.source_field])
        mapped_campaign_expr = self._apply_campaign_name_mappings(campaign_field_expr, source_field_expr)

        outer_select: list[ast.Expr] = [
            ast.Alias(alias=self.config.campaign_field, expr=mapped_campaign_expr),
            ast.Field(chain=[self.config.source_field]),
        ]

        # Add conversion goal columns
        for processor in self.processors:
            outer_select.append(ast.Field(chain=[self.config.get_conversion_goal_column_name(processor.index)]))

        wrapped_query = ast.SelectQuery(
            select=outer_select,
            select_from=ast.JoinExpr(table=final_query),
        )

        return ast.CTE(name=UNIFIED_CONVERSION_GOALS_CTE_ALIAS, expr=wrapped_query, cte_type="subquery")

    def _apply_campaign_name_mappings(self, campaign_expr: ast.Expr, source_expr: ast.Expr) -> ast.Expr:
        """Apply campaign name mappings from team config"""
        # Get team from first processor (all processors have the same team)
        if not self.processors or not self.processors[0].team:
            return campaign_expr

        team = self.processors[0].team

        try:
            campaign_mappings = team.marketing_analytics_config.campaign_name_mappings
        except Exception:
            return campaign_expr

        if not campaign_mappings:
            return campaign_expr

        conditions_and_results: list[ast.Expr] = []
        lowercase_campaign = ast.Call(name="lower", args=[campaign_expr])
        lowercase_source = ast.Call(name="lower", args=[source_expr])

        for external_source, source_mappings in campaign_mappings.items():
            if not source_mappings:
                continue

            # Get utm_source values for this adapter
            adapter_class = MarketingSourceFactory._adapter_registry.get(external_source)
            if not adapter_class:
                continue

            source_mapping = adapter_class.get_source_identifier_mapping()
            utm_sources = []
            for alternatives in source_mapping.values():
                utm_sources.extend(alternatives)

            if not utm_sources:
                continue

            # Build source condition once for this adapter
            source_condition = ast.Call(
                name="in",
                args=[
                    lowercase_source,
                    ast.Array(exprs=[ast.Constant(value=s.lower()) for s in utm_sources]),
                ],
            )

            # Add condition/result pairs for each campaign mapping
            for clean_name, raw_values in source_mappings.items():
                if not raw_values:
                    continue

                campaign_condition = ast.Call(
                    name="in",
                    args=[
                        lowercase_campaign,
                        ast.Array(exprs=[ast.Constant(value=val.lower()) for val in raw_values]),
                    ],
                )

                # Combine source and campaign conditions
                combined_condition = ast.Call(name="and", args=[source_condition, campaign_condition])

                conditions_and_results.append(combined_condition)
                conditions_and_results.append(ast.Constant(value=clean_name))

        # If no mappings were added, return original campaign
        if not conditions_and_results:
            return campaign_expr

        # Add default case (original campaign)
        conditions_and_results.append(campaign_expr)

        # Build multiIf with all conditions
        return ast.Call(name="multiIf", args=conditions_and_results)

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
