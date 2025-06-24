from functools import cached_property
from datetime import datetime
import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.schema import MarketingAnalyticsTableQuery, MarketingAnalyticsTableQueryResponse, CachedMarketingAnalyticsTableQueryResponse

from .constants import (
    DEFAULT_CURRENCY, DEFAULT_LIMIT, PAGINATION_EXTRA, FALLBACK_COST_VALUE,
    TABLE_COLUMNS, DEFAULT_MARKETING_ANALYTICS_COLUMNS, CTR_PERCENTAGE_MULTIPLIER,
    QUERY_CONFIG
)
from .utils import (
    get_marketing_analytics_columns_with_conversion_goals, get_marketing_config_value, 
    ConversionGoalProcessor, get_global_property_conditions, convert_team_conversion_goals_to_objects
)
from .adapters.factory import MarketingSourceFactory
from .adapters.base import QueryContext

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
        return MarketingSourceFactory(team=self.team)

    def _get_marketing_source_adapters(self):
        """Get marketing source adapters using the new adapter architecture"""
        try:
            adapters = self._factory.create_adapters()
            valid_adapters = self._factory.get_valid_adapters(adapters)
            
            logger.info(f"Found {len(valid_adapters)} valid marketing source adapters")
            
            return valid_adapters
            
        except Exception as e:
            logger.error("Error getting marketing source adapters", error=str(e))
            return []

    def to_query(self) -> ast.SelectQuery:
        """Generate the HogQL query using the new adapter architecture"""
        with self.timings.measure("marketing_analytics_table_query"):
            
            # Get marketing source adapters
            adapters = self._get_marketing_source_adapters()
            
            # Create query context for all adapters
            context = QueryContext(
                date_range=self.query_date_range,
                team=self.team,
                global_filters=get_global_property_conditions(self.query, self.team),
                base_currency=getattr(self.team, 'primary_currency', DEFAULT_CURRENCY)
            )
            
            # Build the union query string using the factory
            union_query_string = self._factory.build_union_query(adapters, context)
            
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
        """Build the WITH clause including campaign_costs CTE and conversion goal CTEs"""
        # Build the campaign_costs CTE
        with_clause = f"""
WITH campaign_costs AS (
SELECT 
    {TABLE_COLUMNS['campaign_name']},
    {TABLE_COLUMNS['source_name']},
    sum({TABLE_COLUMNS['cost']}) as total_cost,
    sum({TABLE_COLUMNS['clicks']}) as total_clicks,
    sum({TABLE_COLUMNS['impressions']}) as total_impressions
FROM (
    {union_query_string}
)
GROUP BY {TABLE_COLUMNS['campaign_name']}, {TABLE_COLUMNS['source_name']}
)"""
        
        # Add conversion goal CTEs if any
        if processors:
            conversion_goal_ctes = self._generate_conversion_goal_ctes_from_processors(processors)
            if conversion_goal_ctes:
                with_clause += f", {conversion_goal_ctes}"
        
        return with_clause

    def _build_order_by_clause(self) -> str:
        """Build the ORDER BY clause with proper null handling"""
        order_by_parts = []
        
        if hasattr(self.query, 'orderBy') and self.query.orderBy:
            for order_expr in self.query.orderBy:
                # Fix ordering expressions for null handling
                if 'nullif(' in order_expr and '.conversion_' in order_expr:
                    if order_expr.strip().endswith(' ASC'):
                        calc_part = order_expr.replace(' ASC', '').strip()
                        order_expr = f"COALESCE({calc_part}, {FALLBACK_COST_VALUE}) ASC"
                    elif order_expr.strip().endswith(' DESC'):
                        calc_part = order_expr.replace(' DESC', '').strip()
                        order_expr = f"COALESCE({calc_part}, -{FALLBACK_COST_VALUE}) DESC"
                    else:
                        order_expr = f"COALESCE({order_expr}, {FALLBACK_COST_VALUE})"
                order_by_parts.append(order_expr)
        else:
            order_by_parts = ["cc.total_cost DESC"]
        
        return "ORDER BY " + ", ".join(order_by_parts) if order_by_parts else ""

    def _build_limit_offset(self) -> str:
        """Build the LIMIT and OFFSET clause"""
        limit = self.query.limit or DEFAULT_LIMIT
        offset = self.query.offset or 0
        actual_limit = limit + PAGINATION_EXTRA  # Request one extra for pagination
        
        return f"LIMIT {actual_limit}\nOFFSET {offset}"

    def _build_select_clause(self, processors: list) -> str:
        """Build the SELECT clause with base columns and conversion goal columns"""
        # Get conversion goal components (processors already created and passed in)
        if processors:
            conversion_joins = self._generate_conversion_goal_joins_from_processors(processors)
            conversion_columns = self._generate_conversion_goal_selects_from_processors(processors)
        else:
            conversion_joins = ""
            conversion_columns = ""
        
        # Build base columns
        decimal_precision = QUERY_CONFIG['decimal_precision']
        base_columns = f"""    cc.campaign_name as "Campaign",
    cc.source_name as "Source",
    round(cc.total_cost, {decimal_precision}) as "Total Cost",
    round(cc.total_clicks, 0) as "Total Clicks", 
    round(cc.total_impressions, 0) as "Total Impressions",
    round(cc.total_cost / nullif(cc.total_clicks, 0), {decimal_precision}) as "Cost per Click",
    round(cc.total_clicks / nullif(cc.total_impressions, 0) * {CTR_PERCENTAGE_MULTIPLIER}, {decimal_precision}) as "CTR\""""
        
        # Combine base and conversion goal columns
        all_columns = base_columns
        if conversion_columns:
            all_columns += f",\n{conversion_columns}"
        
        return f"""SELECT 
{all_columns}
FROM campaign_costs cc
{conversion_joins}"""

    def _create_conversion_goal_processors(self, conversion_goals: list) -> list:
        """Create conversion goal processors for reuse across different methods"""
        processors = []
        for index, conversion_goal in enumerate(conversion_goals):
            processor = ConversionGoalProcessor(
                goal=conversion_goal,
                index=index,
                team=self.team,
                query_date_range=self.query_date_range
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
            additional_conditions = self._build_where_conditions(
                include_date_range=True,
                include_global_filters=True,
                date_field=date_field,
                use_date_not_datetime=True  # Conversion goals use toDate instead of toDateTime
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

    def _generate_conversion_goal_selects_from_processors(self, processors: list) -> str:
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
        try:
            from posthog.models import Team
            team = Team.objects.get(pk=self.team.pk)
            marketing_config = getattr(team, 'marketing_analytics_config', None)
            
            team_conversion_goals = []
            if marketing_config:
                team_conversion_goals = get_marketing_config_value(marketing_config, 'conversion_goals', [])
            
            # Convert to proper ConversionGoalFilter objects
            converted_goals = convert_team_conversion_goals_to_objects(team_conversion_goals, self.team.pk)

            return converted_goals
            
        except Exception as e:
            logger.error("Error getting team conversion goals", error=str(e), extra={
                "team_id": self.team.pk
            })
            return []

    def _build_where_conditions(self, base_conditions=None, include_date_range=True, 
                              include_global_filters=True, date_field='timestamp', 
                              use_date_not_datetime=False):
        """Build WHERE conditions with common patterns"""
        conditions = base_conditions or []
        
        if include_date_range:
            if use_date_not_datetime:
                # For conversion goals that use toDate instead of toDateTime
                date_cast = date_field
                conditions.extend([
                    f"{date_cast} >= toDate('{self.query_date_range.date_from_str}')",
                    f"{date_cast} <= toDate('{self.query_date_range.date_to_str}')"
                ])
            else:
                date_cast = f"toDateTime({date_field})" if date_field != 'timestamp' else date_field
                conditions.extend([
                    f"{date_cast} >= toDateTime('{self.query_date_range.date_from_str}')",
                    f"{date_cast} <= toDateTime('{self.query_date_range.date_to_str}')"
                ])
        
        if include_global_filters:
            conditions.extend(get_global_property_conditions(self.query, self.team))
        
        return conditions
