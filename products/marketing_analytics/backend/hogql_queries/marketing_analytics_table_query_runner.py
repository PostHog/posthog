from functools import cached_property
from datetime import datetime
import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.schema import (
    MarketingAnalyticsTableQuery,
    MarketingAnalyticsTableQueryResponse,
    CachedMarketingAnalyticsTableQueryResponse,
)
from .conversion_goal_processor import ConversionGoalProcessor

from .constants import (
    CAMPAIGN_COST_CTE_NAME,
    CONVERSION_GOAL_PREFIX,
    DEFAULT_LIMIT,
    PAGINATION_EXTRA,
    FALLBACK_COST_VALUE,
    DEFAULT_MARKETING_ANALYTICS_COLUMNS,
    CTR_PERCENTAGE_MULTIPLIER,
    DECIMAL_PRECISION,
    TOTAL_CLICKS_FIELD,
    TOTAL_COST_FIELD,
    TOTAL_IMPRESSIONS_FIELD,
)
from .utils import (
    get_marketing_analytics_columns_with_conversion_goals,
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

    def select_input_raw(self) -> list[str]:
        """Get the raw select input, using defaults if none specified"""
        return DEFAULT_MARKETING_ANALYTICS_COLUMNS if len(self.query.select) == 0 else self.query.select

    @cached_property
    def _factory(self):
        """Cached factory instance for reuse"""

        # Create query context for all adapters
        context = QueryContext(
            date_range=self.query_date_range,
            team=self.team,
            base_currency=self.team.base_currency,
        )
        return MarketingSourceFactory(context=context)

    def _get_marketing_source_adapters(self):
        """Get marketing source adapters using the new adapter architecture"""
        try:
            adapters = self._factory.create_adapters()
            valid_adapters = self._factory.get_valid_adapters(adapters)

            logger.info(f"Found {len(valid_adapters)} valid marketing source adapters")

            return valid_adapters

        except Exception as e:
            logger.exception("Error getting marketing source adapters", error=str(e))
            return []

    def to_query(self) -> ast.SelectQuery:
        """Generate the HogQL query using the new adapter architecture"""
        with self.timings.measure("marketing_analytics_table_query"):
            # Get marketing source adapters
            adapters = self._get_marketing_source_adapters()

            # Build the union query string using the factory
            union_query_string = self._factory.build_union_query(adapters)

            # Build the final query with ordering and pagination
            final_query_string = self._build_final_query_string(union_query_string)

            return parse_select(final_query_string)

    def calculate(self) -> MarketingAnalyticsTableQueryResponse:
        """Execute the query and return results with pagination support"""
        from posthog.hogql.query import execute_hogql_query

        query = self.to_query()

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

        # Check if there are more results
        has_more = len(results) > requested_limit

        # Trim results to the requested limit if we got extra
        if has_more:
            results = results[:requested_limit]

        # Get conversion goals from team config for column names
        conversion_goals = self._get_team_conversion_goals()

        return MarketingAnalyticsTableQueryResponse(
            results=results,
            columns=get_marketing_analytics_columns_with_conversion_goals(conversion_goals),
            types=response.types,
            hogql=response.hogql,
            timings=response.timings,
            modifiers=self.modifiers,
            hasMore=has_more,
            limit=requested_limit,
            offset=self.query.offset or 0,
        )

    def _build_final_query_string(self, union_query_string: str) -> str:
        """Build the final query with the same structure as frontend"""
        conversion_goals = self._get_team_conversion_goals()

        # Create processors once and reuse across all methods
        processors = self._create_conversion_goal_processors(conversion_goals) if conversion_goals else []

        # Build query components
        with_clause = self._build_with_clause(union_query_string, processors)
        order_by_clause = self._build_order_by_clause()
        limit_offset = self._build_limit_offset()
        select_clause = self._build_select_clause(processors)

        # Assemble final query
        final_query = f"""
{with_clause}
{select_clause}
{order_by_clause}
{limit_offset}
        """.strip()

        return final_query

    def _build_with_clause(self, union_query_string: str, processors: list) -> str:
        """Build the WITH clause including campaign_costs CTE and conversion goal CTEs using AST internally"""
        # Build the campaign_costs CTE using AST internally
        campaign_cost_select_ast = self._build_campaign_cost_select_ast(union_query_string)
        campaign_cost_cte = f"{CAMPAIGN_COST_CTE_NAME} AS (\n{campaign_cost_select_ast.to_hogql()}\n)"

        with_clause = f"WITH {campaign_cost_cte}"

        # Add conversion goal CTEs if any
        if processors:
            conversion_goal_ctes = self._generate_conversion_goal_ctes_from_processors(processors)
            if conversion_goal_ctes:
                with_clause += f", {conversion_goal_ctes}"

        return with_clause

    def _build_campaign_cost_select_ast(self, union_query_string: str) -> ast.SelectQuery:
        """Build the campaign_costs CTE SELECT query using AST internally"""
        # Build SELECT columns for the CTE using AST
        select_columns = [
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
        from posthog.hogql.parser import parse_select

        union_subquery = parse_select(union_query_string)
        union_join_expr = ast.JoinExpr(table=union_subquery)

        # Build GROUP BY using AST
        group_by_exprs = [
            ast.Field(chain=[MarketingSourceAdapter.campaign_name_field]),
            ast.Field(chain=[MarketingSourceAdapter.source_name_field]),
        ]

        # Build the CTE SELECT query
        return ast.SelectQuery(select=select_columns, select_from=union_join_expr, group_by=group_by_exprs)

    def _build_order_by_clause(self) -> str:
        """Build the ORDER BY clause with proper null handling using AST internally"""
        order_by_parts = []

        if hasattr(self.query, "orderBy") and self.query.orderBy:
            for order_expr in self.query.orderBy:
                # Fix ordering expressions for null handling
                if "nullif(" in order_expr and CONVERSION_GOAL_PREFIX in order_expr:
                    if order_expr.strip().endswith(" ASC"):
                        calc_part = order_expr.replace(" ASC", "").strip()
                        # Build AST: COALESCE(calc_part, FALLBACK_COST_VALUE) ASC
                        from posthog.hogql.parser import parse_expr

                        try:
                            calc_expr_ast = parse_expr(calc_part)
                        except:
                            calc_expr_ast = ast.Field(chain=[calc_part])

                        coalesce_ast = ast.Call(
                            name="COALESCE", args=[calc_expr_ast, ast.Constant(value=FALLBACK_COST_VALUE)]
                        )
                        order_expr = f"{coalesce_ast.to_hogql()} ASC"
                    elif order_expr.strip().endswith(" DESC"):
                        calc_part = order_expr.replace(" DESC", "").strip()
                        # Build AST: COALESCE(calc_part, -FALLBACK_COST_VALUE) DESC
                        from posthog.hogql.parser import parse_expr

                        try:
                            calc_expr_ast = parse_expr(calc_part)
                        except:
                            calc_expr_ast = ast.Field(chain=[calc_part])

                        coalesce_ast = ast.Call(
                            name="COALESCE", args=[calc_expr_ast, ast.Constant(value=-FALLBACK_COST_VALUE)]
                        )
                        order_expr = f"{coalesce_ast.to_hogql()} DESC"
                    else:
                        # Build AST: COALESCE(order_expr, FALLBACK_COST_VALUE)
                        from posthog.hogql.parser import parse_expr

                        try:
                            expr_ast = parse_expr(order_expr)
                        except:
                            expr_ast = ast.Field(chain=[order_expr])

                        coalesce_ast = ast.Call(
                            name="COALESCE", args=[expr_ast, ast.Constant(value=FALLBACK_COST_VALUE)]
                        )
                        order_expr = coalesce_ast.to_hogql()
                order_by_parts.append(order_expr)
        else:
            # Build default order by using AST: campaign_costs.total_cost DESC
            default_field_ast = ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_COST_FIELD])
            order_by_parts = [f"{default_field_ast.to_hogql()} DESC"]

        return "ORDER BY " + ", ".join(order_by_parts) if order_by_parts else ""

    def _build_limit_offset(self) -> str:
        """Build the LIMIT and OFFSET clause"""
        limit = self.query.limit or DEFAULT_LIMIT
        offset = self.query.offset or 0
        actual_limit = limit + PAGINATION_EXTRA  # Request one extra for pagination

        return f"LIMIT {actual_limit}\nOFFSET {offset}"

    def _build_select_clause(self, processors: list) -> str:
        """Build the SELECT clause with base columns and conversion goal columns using AST internally"""
        # Get conversion goal components (processors already created and passed in)
        if processors:
            conversion_joins = self._generate_conversion_goal_joins_from_processors(processors)
            conversion_columns = self._generate_conversion_goal_selects_from_processors(processors)
        else:
            conversion_joins = ""
            conversion_columns = ""

        # Build base columns using AST internally
        base_columns_ast = self._build_base_columns_ast()
        base_columns = ",\n".join([f"    {col.to_hogql()}" for col in base_columns_ast])

        # Combine base and conversion goal columns
        all_columns = base_columns
        if conversion_columns:
            all_columns += f",\n{conversion_columns}"

        return f"""SELECT
{all_columns}
FROM {CAMPAIGN_COST_CTE_NAME}
{conversion_joins}"""

    def _build_base_columns_ast(self) -> list[ast.Alias]:
        """Build base columns using AST internally"""
        return [
            # Campaign name
            ast.Alias(
                alias="Campaign",
                expr=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, MarketingSourceAdapter.campaign_name_field]),
            ),
            # Source name
            ast.Alias(
                alias="Source", expr=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, MarketingSourceAdapter.source_name_field])
            ),
            # Total Cost: round(campaign_costs.total_cost, 2)
            ast.Alias(
                alias="Total Cost",
                expr=ast.Call(
                    name="round",
                    args=[
                        ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_COST_FIELD]),
                        ast.Constant(value=DECIMAL_PRECISION),
                    ],
                ),
            ),
            # Total Clicks: round(campaign_costs.total_clicks, 0)
            ast.Alias(
                alias="Total Clicks",
                expr=ast.Call(
                    name="round",
                    args=[ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_CLICKS_FIELD]), ast.Constant(value=0)],
                ),
            ),
            # Total Impressions: round(campaign_costs.total_impressions, 0)
            ast.Alias(
                alias="Total Impressions",
                expr=ast.Call(
                    name="round",
                    args=[ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_IMPRESSIONS_FIELD]), ast.Constant(value=0)],
                ),
            ),
            # Cost per Click: round(total_cost / nullif(total_clicks, 0), 2)
            ast.Alias(
                alias="Cost per Click",
                expr=ast.Call(
                    name="round",
                    args=[
                        ast.ArithmeticOperation(
                            left=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_COST_FIELD]),
                            op=ast.ArithmeticOperationOp.Div,
                            right=ast.Call(
                                name="nullif",
                                args=[
                                    ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_CLICKS_FIELD]),
                                    ast.Constant(value=0),
                                ],
                            ),
                        ),
                        ast.Constant(value=DECIMAL_PRECISION),
                    ],
                ),
            ),
            # CTR: round(total_clicks / nullif(total_impressions, 0) * 100, 2)
            ast.Alias(
                alias="CTR",
                expr=ast.Call(
                    name="round",
                    args=[
                        ast.ArithmeticOperation(
                            left=ast.ArithmeticOperation(
                                left=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_CLICKS_FIELD]),
                                op=ast.ArithmeticOperationOp.Div,
                                right=ast.Call(
                                    name="nullif",
                                    args=[
                                        ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_IMPRESSIONS_FIELD]),
                                        ast.Constant(value=0),
                                    ],
                                ),
                            ),
                            op=ast.ArithmeticOperationOp.Mult,
                            right=ast.Constant(value=CTR_PERCENTAGE_MULTIPLIER),
                        ),
                        ast.Constant(value=DECIMAL_PRECISION),
                    ],
                ),
            ),
        ]

    def _create_conversion_goal_processors(self, conversion_goals: list) -> list:
        """Create conversion goal processors for reuse across different methods"""
        processors = []
        for index, conversion_goal in enumerate(conversion_goals):
            processor = ConversionGoalProcessor(
                goal=conversion_goal, index=index, team=self.team, query_date_range=self.query_date_range
            )
            processors.append(processor)
        return processors

    def _generate_conversion_goal_ctes_from_processors(self, processors: list) -> str:
        """Generate CTEs for conversion goals with proper property filtering"""
        if not processors:
            return ""

        ctes = []
        for processor in processors:
            # Build additional conditions (date range and global filters)
            date_field = processor.get_date_field()
            additional_conditions = self._get_where_conditions(
                include_date_range=True,
                date_field=date_field,
                use_date_not_datetime=True,  # Conversion goals use toDate instead of toDateTime
            )

            # Let the processor generate its own CTE query
            cte_query = processor.generate_cte_query(additional_conditions)
            ctes.append(cte_query)

        return ",\n".join(ctes)

    def _generate_conversion_goal_joins_from_processors(self, processors: list) -> str:
        """Generate JOIN clauses for conversion goals"""
        if not processors:
            return ""

        joins = []
        for processor in processors:
            # Let the processor generate its own JOIN clause
            join_clause = processor.generate_join_clause()
            joins.append(join_clause)

        return "\n".join(joins)

    def _generate_conversion_goal_selects_from_processors(self, processors: list[ConversionGoalProcessor]) -> str:
        """Generate SELECT columns for conversion goals"""
        if not processors:
            return ""

        all_selects = []
        for processor in processors:
            # Let the processor generate its own SELECT columns
            select_columns = processor.generate_select_columns()
            all_selects.extend(select_columns)

        return ",\n".join(all_selects)

    def _get_team_conversion_goals(self):
        """Get conversion goals from team marketing analytics config and convert to proper objects"""
        conversion_goals = self.team.marketing_analytics_config.conversion_goals
        return convert_team_conversion_goals_to_objects(conversion_goals, self.team.pk)

    def _get_where_conditions(
        self,
        base_conditions=None,
        include_date_range=True,
        date_field="timestamp",
        use_date_not_datetime=False,
    ) -> list[ast.Expr]:
        """Build WHERE conditions with common patterns using AST internally"""
        conditions = base_conditions or []

        if include_date_range:
            if use_date_not_datetime:
                # For conversion goals that use toDate instead of toDateTime
                # Build AST: date_field >= toDate('date_from')
                date_field_ast = ast.Field(chain=[date_field])
                from_date_ast = ast.Call(name="toDate", args=[ast.Constant(value=self.query_date_range.date_from_str)])
                to_date_ast = ast.Call(name="toDate", args=[ast.Constant(value=self.query_date_range.date_to_str)])

                gte_condition = ast.CompareOperation(
                    left=date_field_ast, op=ast.CompareOperationOp.GtEq, right=from_date_ast
                )
                lte_condition = ast.CompareOperation(
                    left=date_field_ast, op=ast.CompareOperationOp.LtEq, right=to_date_ast
                )

                conditions.extend([gte_condition, lte_condition])
            else:
                # Build AST for regular datetime conditions
                if date_field != "timestamp":
                    date_cast_ast = ast.Call(name="toDateTime", args=[ast.Field(chain=[date_field])])
                else:
                    date_cast_ast = ast.Field(chain=[date_field])

                from_datetime_ast = ast.Call(
                    name="toDateTime", args=[ast.Constant(value=self.query_date_range.date_from_str)]
                )
                to_datetime_ast = ast.Call(
                    name="toDateTime", args=[ast.Constant(value=self.query_date_range.date_to_str)]
                )

                gte_condition = ast.CompareOperation(
                    left=date_cast_ast, op=ast.CompareOperationOp.GtEq, right=from_datetime_ast
                )
                lte_condition = ast.CompareOperation(
                    left=date_cast_ast, op=ast.CompareOperationOp.LtEq, right=to_datetime_ast
                )

                conditions.extend([gte_condition, lte_condition])

        return conditions
