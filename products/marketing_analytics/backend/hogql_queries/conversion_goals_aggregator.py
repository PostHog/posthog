from posthog.schema import MarketingAnalyticsBaseColumns

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
            # Note: base_query schema is: [0]=match_key, [1]=campaign, [2]=id, [3]=source, [4]=conversion
            enhanced_select = [
                # Keep campaign, id, and source (skip match_key at [0])
                base_query.select[1],  # campaign
                base_query.select[2],  # id
                base_query.select[3],  # source
            ]

            # Add columns for all conversion goals (this one gets the actual value, others get 0)
            for p in self.processors:
                if p.index == processor.index:
                    # This is the current processor - use the actual conversion value
                    # Extract the expression from the alias to avoid double aliasing
                    # Position [4] is the conversion value (after match_key, campaign, id, source)
                    conversion_expr = base_query.select[4]
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

        # Step 3: Create final aggregation query that sums all conversion goals by campaign/id/source
        # Apply campaign name mappings HERE so we only need one GROUP BY
        subquery_alias = "conv"

        # Include the subquery alias in field references so they work correctly in the outer query
        campaign_field_expr = ast.Field(chain=[subquery_alias, self.config.campaign_field])
        id_field_expr = ast.Field(chain=[subquery_alias, self.config.id_field])
        source_field_expr = ast.Field(chain=[subquery_alias, self.config.source_field])

        # Get mapped expressions - these will be used in both SELECT and GROUP BY
        mapped_campaign_expr, mapped_id_expr = self._apply_campaign_name_mappings(
            campaign_field_expr, id_field_expr, source_field_expr
        )

        # Build SELECT with mapped values
        final_select: list[ast.Expr] = [
            ast.Alias(alias=self.config.campaign_field, expr=mapped_campaign_expr),
            ast.Alias(alias=self.config.id_field, expr=mapped_id_expr),
            ast.Alias(alias=self.config.source_field, expr=source_field_expr),
            # match_key for conversion goals is always utm_campaign - UTM tracking has no campaign ID param.
            # Users who prefer campaign_id matching must put IDs in their utm_campaign parameter.
            # Ad adapters output their match_key based on team prefs; this enables the JOIN to work.
            ast.Alias(alias=self.config.match_key_field, expr=mapped_campaign_expr),
        ]

        # Add each conversion goal as a summed column
        for processor in self.processors:
            final_select.append(
                ast.Alias(
                    alias=self.config.get_conversion_goal_column_name(processor.index),
                    expr=ast.Call(
                        name="sum",
                        args=[
                            ast.Field(
                                chain=[subquery_alias, self.config.get_conversion_goal_column_name(processor.index)]
                            )
                        ],
                    ),
                )
            )

        # GROUP BY the mapped expressions (same expressions used in SELECT)
        # This ensures rows with the same mapped values are consolidated in a single pass
        # Note: For conversion goals, match_key is derived from utm_campaign (same as mapped_campaign)
        # since events don't have platform-specific campaign IDs
        final_query = ast.SelectQuery(
            select=final_select,
            select_from=ast.JoinExpr(table=union_query, alias=subquery_alias),
            group_by=[
                mapped_campaign_expr,
                mapped_id_expr,
                source_field_expr,
            ],
        )

        return ast.CTE(name=UNIFIED_CONVERSION_GOALS_CTE_ALIAS, expr=final_query, cte_type="subquery")

    def _get_campaign_field_preference(self, external_source: str) -> str:
        """
        Get campaign field matching preference for a given integration from team config.

        Returns: "campaign_name" or "campaign_id"

        Defaults to campaign_name if no preference set (backward compatible).
        """
        if not self.processors or not self.processors[0].team:
            return "campaign_name"

        team = self.processors[0].team

        try:
            preferences = team.marketing_analytics_config.campaign_field_preferences
            integration_prefs = preferences.get(external_source, {})
            return integration_prefs.get("match_field", "campaign_name")
        except Exception:
            return "campaign_name"

    def _apply_campaign_name_mappings(
        self, campaign_expr: ast.Expr, id_expr: ast.Expr, source_expr: ast.Expr
    ) -> tuple[ast.Expr, ast.Expr]:
        """
        Apply campaign name mappings from team config.

        Returns a tuple of (mapped_campaign_expr, mapped_id_expr).

        When a source is configured to match on campaign_id, the mapping will:
        - Map utm_campaign values to campaign_id values
        - Keep campaign_name unchanged (from the original data)

        When a source is configured to match on campaign_name (default), the mapping will:
        - Map utm_campaign values to campaign_name values
        - Keep campaign_id unchanged
        """
        if not self.processors or not self.processors[0].team:
            return campaign_expr, id_expr

        team = self.processors[0].team

        try:
            campaign_mappings = team.marketing_analytics_config.campaign_name_mappings
        except Exception:
            return campaign_expr, id_expr

        if not campaign_mappings:
            return campaign_expr, id_expr

        # Build separate mapping expressions for campaign_name and campaign_id
        campaign_name_conditions: list[ast.Expr] = []
        campaign_id_conditions: list[ast.Expr] = []

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

            # Get the match field preference for this source
            match_field = self._get_campaign_field_preference(external_source)

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

                # The raw_values are utm_campaign values that should be mapped to clean_name
                campaign_condition = ast.Call(
                    name="in",
                    args=[
                        lowercase_campaign,
                        ast.Array(exprs=[ast.Constant(value=val.lower()) for val in raw_values]),
                    ],
                )

                # Combine source and campaign conditions
                combined_condition = ast.Call(name="and", args=[source_condition, campaign_condition])

                if match_field == "campaign_id":
                    # When matching on campaign_id, map utm_campaign -> campaign_id
                    # The clean_name is the campaign_id value
                    campaign_id_conditions.append(combined_condition)
                    campaign_id_conditions.append(ast.Constant(value=clean_name))
                else:
                    # When matching on campaign_name (default), map utm_campaign -> campaign_name
                    # The clean_name is the campaign_name value
                    campaign_name_conditions.append(combined_condition)
                    campaign_name_conditions.append(ast.Constant(value=clean_name))

        # Build final expressions
        mapped_campaign_expr = campaign_expr
        mapped_id_expr = id_expr

        if campaign_name_conditions:
            campaign_name_conditions.append(campaign_expr)
            mapped_campaign_expr = ast.Call(name="multiIf", args=campaign_name_conditions)

        if campaign_id_conditions:
            campaign_id_conditions.append(id_expr)
            mapped_id_expr = ast.Call(name="multiIf", args=campaign_id_conditions)

        return mapped_campaign_expr, mapped_id_expr

    def get_conversion_goal_columns(self, include_cost_per: bool = True) -> dict[str, ast.Alias]:
        """Get the column mappings for accessing conversion goals from the unified CTE

        Args:
            include_cost_per: If True, include "Cost per conversion" columns that reference
                campaign_costs CTE. Set to False for queries that don't join with
                campaign_costs (e.g., non-integrated conversions).
        """
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
            columns[goal_name] = conversion_goal_alias

            # Cost per conversion column (only if requested and campaign_costs is available)
            if include_cost_per:
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
                columns[f"{self.config.cost_per_prefix} {goal_name}"] = cost_per_goal_alias

        return columns

    def get_coalesce_fallback_columns(self) -> dict[str, ast.Expr]:
        """Get COALESCE columns that fall back to unified conversion goals for campaign/id/source"""
        # Use the config group_by_fields to build COALESCE expressions
        campaign_field, id_field, source_field = self.config.group_by_fields

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

        id_args = [
            ast.Call(
                name="nullif",
                args=[
                    ast.Field(chain=self.config.get_campaign_cost_field_chain(id_field)),
                    ast.Constant(value=""),
                ],
            ),
            ast.Call(
                name="nullif",
                args=[
                    ast.Field(chain=self.config.get_unified_conversion_field_chain(id_field)),
                    ast.Constant(value=""),
                ],
            ),
            ast.Constant(value="-"),  # "-" for organic/conversion ID (not applicable)
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
            MarketingAnalyticsBaseColumns.ID: ast.Alias(
                alias=MarketingAnalyticsBaseColumns.ID, expr=ast.Call(name="coalesce", args=id_args)
            ),
            self.config.source_column_alias: ast.Alias(
                alias=self.config.source_column_alias, expr=ast.Call(name="coalesce", args=source_args)
            ),
        }
