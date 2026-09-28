from posthog.schema import MarketingAnalyticsBaseColumns, MarketingAnalyticsDrillDownLevel

from posthog.hogql import ast

from posthog.hogql_queries.utils.caller_context import map_in_caller_context
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.marketing_analytics.backend.hogql_queries.constants import (
    CAC_COLUMN_SUFFIX,
    ROAS_COLUMN,
    UNIFIED_CONVERSION_GOALS_CTE_ALIAS,
    UNKNOWN_CHANNEL,
)

from .conversion_goal_processor import ConversionGoalProcessor, SharedTouchpointsPrecompute
from .marketing_analytics_config import MarketingAnalyticsConfig


class ConversionGoalsAggregator:
    """
    A dedicated query runner that creates a single unified table of all conversion goals
    grouped by campaign and source
    """

    def __init__(self, processors: list[ConversionGoalProcessor], config: MarketingAnalyticsConfig):
        self.processors = processors
        self.config = config

    def _count_processors(self) -> list[ConversionGoalProcessor]:
        """Customer goals whose own column holds money, so cost per customer needs a count too.

        A customer goal that already counts (or uniques, for `dau`) is its own denominator.
        """
        return [p for p in self.processors if p.goal.counts_as_customer and p.sums_a_property()]

    def generate_unified_cte(self, date_range: QueryDateRange, additional_conditions_getter) -> ast.CTE:
        """Generate a single CTE that contains all conversion goals aggregated by campaign/source"""
        if not self.processors:
            raise ValueError("Cannot create unified CTE without conversion goal processors")

        # Goal-agnostic, so one handle materializes it once per read rather than once per goal. Reading
        # processor 0 for the flag is safe: every processor in a read came from the same query.
        touchpoints = SharedTouchpointsPrecompute(
            self.processors[0].team, self.config, self.processors[0].filter_test_accounts
        )

        # Step 1: Generate individual conversion goal queries, parallelised across goals
        # so ensure_precomputed's PG+Redis+ClickHouse round-trips collapse to max(overhead).
        def _build_base_query(processor: ConversionGoalProcessor) -> ast.SelectQuery:
            date_field = processor.get_date_field()
            additional_conditions = additional_conditions_getter(
                date_range=date_range,
                include_date_range=True,
                date_field=date_field,
                use_date_not_datetime=True,
            )
            return processor.generate_cte_query(
                additional_conditions,
                date_from=date_range.date_from(),
                date_to=date_range.date_to(),
                touchpoints=touchpoints,
            )

        # The caller's query tags must reach the workers: a background revalidation tags its own
        # ensures CACHE_WARMUP so they skip the grace and actually recompute, and dropping that tag
        # would make the revalidation serve itself stale and never refresh.
        base_queries = map_in_caller_context(_build_base_query, self.processors, thread_name_prefix="ma_cte")

        count_processors = self._count_processors()

        conversion_subqueries = []
        for processor, base_query in zip(self.processors, base_queries):
            # Transform the query to include a column for this specific conversion goal
            # and zero columns for all other conversion goals
            # Note: base_query schema is: [0]=match_key, [1]=campaign, [2]=id, [3]=source, [4]=conversion
            enhanced_select = [
                base_query.select[0],  # match_key
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

                # Every subquery in the UNION has to carry the same columns, so the count
                # rides along for all of them, actual for its owner and 0 elsewhere. Same
                # grouping as the value column, so it counts that goal's conversions.
                if p in count_processors:
                    enhanced_select.append(
                        ast.Alias(
                            alias=self.config.get_conversion_goal_count_column_name(p.index),
                            expr=p.get_count_field() if p.index == processor.index else ast.Constant(value=0),
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

        # Step 3: Create final aggregation query that sums all conversion goals
        subquery_alias = "conv"
        level = self.config.drill_down_level

        # Include the subquery alias in field references so they work correctly in the outer query
        campaign_field_expr = ast.Field(chain=[subquery_alias, self.config.campaign_field])
        id_field_expr = ast.Field(chain=[subquery_alias, self.config.id_field])
        source_field_expr = ast.Field(chain=[subquery_alias, self.config.source_field])
        match_key_expr = ast.Field(chain=[subquery_alias, self.config.match_key_field])

        if level in (
            MarketingAnalyticsDrillDownLevel.CHANNEL,
            MarketingAnalyticsDrillDownLevel.SOURCE,
            MarketingAnalyticsDrillDownLevel.MEDIUM,
            MarketingAnalyticsDrillDownLevel.CONTENT,
            MarketingAnalyticsDrillDownLevel.TERM,
        ):
            final_select: list[ast.Expr] = [
                ast.Alias(alias=self.config.campaign_field, expr=campaign_field_expr),
                ast.Alias(alias=self.config.id_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.source_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.match_key_field, expr=ast.Constant(value="")),
            ]
            group_by_exprs: list[ast.Expr] = [campaign_field_expr]
        elif level == MarketingAnalyticsDrillDownLevel.CHANNEL_SOURCE:
            # campaign_field holds the channel; source stays a real key. No campaign name
            # mappings here — they key off campaign, which this level doesn't group by.
            final_select = [
                ast.Alias(alias=self.config.campaign_field, expr=campaign_field_expr),
                ast.Alias(alias=self.config.id_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.source_field, expr=source_field_expr),
                ast.Alias(alias=self.config.match_key_field, expr=ast.Constant(value="")),
            ]
            group_by_exprs = [campaign_field_expr, source_field_expr]
        else:
            # The cost join has one row per match key and source, regardless of the raw aliases each goal saw.
            final_select = [
                ast.Alias(alias=self.config.campaign_field, expr=ast.Call(name="min", args=[campaign_field_expr])),
                ast.Alias(alias=self.config.id_field, expr=ast.Call(name="min", args=[id_field_expr])),
                ast.Alias(alias=self.config.source_field, expr=source_field_expr),
                ast.Alias(alias=self.config.match_key_field, expr=match_key_expr),
            ]
            group_by_exprs = [match_key_expr, source_field_expr]

        # Add each conversion goal as a summed column
        count_processors = self._count_processors()
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
            if processor in count_processors:
                count_column = self.config.get_conversion_goal_count_column_name(processor.index)
                final_select.append(
                    ast.Alias(
                        alias=count_column,
                        expr=ast.Call(name="sum", args=[ast.Field(chain=[subquery_alias, count_column])]),
                    )
                )

        final_query = ast.SelectQuery(
            select=final_select,
            select_from=ast.JoinExpr(table=union_query, alias=subquery_alias),
            group_by=group_by_exprs,
        )

        return ast.CTE(name=UNIFIED_CONVERSION_GOALS_CTE_ALIAS, expr=final_query, cte_type="subquery")

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

        # Both need campaign_costs joined, since spend is the denominator. ROAS also needs the
        # goal to hold money: a counting goal in its numerator reads 200 signups against $100
        # as "ROAS 2.0". CAC has no such restriction — a summing goal contributes its count
        # column instead of its value, so a purchase goal flagged as both still works.
        if include_cost_per:
            revenue_processors = [p for p in self.processors if p.goal.counts_as_revenue and p.sums_a_property()]
            if revenue_processors:
                columns[ROAS_COLUMN] = self._build_roas_column(revenue_processors)

            customer_processors = [p for p in self.processors if p.goal.counts_as_customer]
            if customer_processors:
                cac_alias = f"{self.config.cost_per_prefix} {CAC_COLUMN_SUFFIX}"
                columns[cac_alias] = self._build_cac_column(customer_processors, cac_alias)

        return columns

    def _build_roas_column(self, revenue_processors: list[ConversionGoalProcessor]) -> ast.Alias:
        total_revenue = self._sum_conversion_values(revenue_processors)
        total_cost = ast.Field(chain=self.config.get_campaign_cost_field_chain(self.config.total_cost_field))
        return ast.Alias(
            alias=ROAS_COLUMN,
            expr=ast.Call(
                name="round",
                args=[
                    ast.ArithmeticOperation(
                        left=total_revenue,
                        op=ast.ArithmeticOperationOp.Div,
                        right=ast.Call(name="nullif", args=[total_cost, ast.Constant(value=0)]),
                    ),
                    ast.Constant(value=2),
                ],
            ),
        )

    def _build_cac_column(self, customer_processors: list[ConversionGoalProcessor], alias: str) -> ast.Alias:
        # Each customer goal contributes its conversion count, which is right only for a
        # once-per-person moment: a repeatable event overcounts, and `dau` is the closest fit.
        total_customers = self._sum_conversion_values(customer_processors, prefer_count=True)
        total_cost = ast.Field(chain=self.config.get_campaign_cost_field_chain(self.config.total_cost_field))
        return ast.Alias(
            alias=alias,
            expr=ast.Call(
                name="round",
                args=[
                    ast.ArithmeticOperation(
                        left=total_cost,
                        op=ast.ArithmeticOperationOp.Div,
                        right=ast.Call(name="nullif", args=[total_customers, ast.Constant(value=0)]),
                    ),
                    ast.Constant(value=2),
                ],
            ),
        )

    def _sum_conversion_values(
        self, processors: list[ConversionGoalProcessor], *, prefer_count: bool = False
    ) -> ast.Expr:
        """Sum the unified-CTE columns of the given goals into one expression.

        With `prefer_count`, a goal whose own column holds a summed amount contributes its
        paired count column instead — the only way a summing goal can answer "how many".
        """

        def column_for(p: ConversionGoalProcessor) -> str:
            if prefer_count and p.sums_a_property():
                return self.config.get_conversion_goal_count_column_name(p.index)
            return self.config.get_conversion_goal_column_name(p.index)

        fields = [ast.Field(chain=self.config.get_unified_conversion_field_chain(column_for(p))) for p in processors]
        total: ast.Expr = fields[0]
        for field in fields[1:]:
            total = ast.ArithmeticOperation(left=total, op=ast.ArithmeticOperationOp.Add, right=field)
        return total

    def get_coalesce_fallback_columns(self, campaign_costs_joined: bool = True) -> dict[str, ast.Expr]:
        """Get COALESCE columns that fall back to unified conversion goals for campaign/id/source.

        Args:
            campaign_costs_joined: Whether the outer query joins with campaign_costs CTE.
                When False (e.g. UTM levels that bypass campaign_costs), the COALESCE
                only references the unified conversion goals side.
        """
        level = self.config.drill_down_level
        group_by_fields = self.config.group_by_fields

        # CHANNEL_SOURCE only needs the grouping alias here; `_append_sessions_join` overwrites it
        # with a coalesce that also spans the sessions side.
        if level in (
            MarketingAnalyticsDrillDownLevel.CHANNEL,
            MarketingAnalyticsDrillDownLevel.CHANNEL_SOURCE,
            MarketingAnalyticsDrillDownLevel.SOURCE,
            MarketingAnalyticsDrillDownLevel.MEDIUM,
            MarketingAnalyticsDrillDownLevel.CONTENT,
            MarketingAnalyticsDrillDownLevel.TERM,
        ):
            campaign_field = self.config.campaign_field
            # "(none)" = BREAKDOWN_NULL_DISPLAY for UTM fields.
            fallback_map = {
                MarketingAnalyticsDrillDownLevel.CHANNEL: UNKNOWN_CHANNEL,
                MarketingAnalyticsDrillDownLevel.CHANNEL_SOURCE: UNKNOWN_CHANNEL,
                MarketingAnalyticsDrillDownLevel.SOURCE: self.config.organic_source,
                MarketingAnalyticsDrillDownLevel.MEDIUM: "(none)",
                MarketingAnalyticsDrillDownLevel.CONTENT: "(none)",
                MarketingAnalyticsDrillDownLevel.TERM: "(none)",
            }
            fallback = fallback_map[level]
            campaign_alias = self.config.get_campaign_column_alias()
            campaign_args: list[ast.Expr] = []
            if campaign_costs_joined:
                campaign_args.append(
                    ast.Call(
                        name="nullif",
                        args=[
                            ast.Field(chain=self.config.get_campaign_cost_field_chain(campaign_field)),
                            ast.Constant(value=""),
                        ],
                    )
                )
            campaign_args.extend(
                [
                    ast.Call(
                        name="nullif",
                        args=[
                            ast.Field(chain=self.config.get_unified_conversion_field_chain(campaign_field)),
                            ast.Constant(value=""),
                        ],
                    ),
                    ast.Constant(value=fallback),
                ]
            )
            return {
                campaign_alias: ast.Alias(alias=campaign_alias, expr=ast.Call(name="coalesce", args=campaign_args)),
            }

        # Campaign level (default) — 3 fields
        campaign_field, id_field, source_field = group_by_fields
        campaign_alias = self.config.get_campaign_column_alias()

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
            ast.Constant(value="-"),
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
            campaign_alias: ast.Alias(alias=campaign_alias, expr=ast.Call(name="coalesce", args=campaign_args)),
            MarketingAnalyticsBaseColumns.ID: ast.Alias(
                alias=MarketingAnalyticsBaseColumns.ID, expr=ast.Call(name="coalesce", args=id_args)
            ),
            self.config.source_column_alias: ast.Alias(
                alias=self.config.source_column_alias, expr=ast.Call(name="coalesce", args=source_args)
            ),
        }
