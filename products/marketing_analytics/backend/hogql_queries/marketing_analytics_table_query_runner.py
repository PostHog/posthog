from functools import cached_property
from datetime import datetime
import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.schema import MarketingAnalyticsTableQuery, MarketingAnalyticsTableQueryResponse, CachedMarketingAnalyticsTableQueryResponse, ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3

from .constants import (
    DEFAULT_CURRENCY, DEFAULT_LIMIT, PAGINATION_EXTRA, FALLBACK_COST_VALUE,
    UNKNOWN_CAMPAIGN, UNKNOWN_SOURCE, TABLE_COLUMNS, DEFAULT_MARKETING_ANALYTICS_COLUMNS,
    MARKETING_ANALYTICS_SCHEMA, VALID_NATIVE_MARKETING_SOURCES,
    NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS
)
from .utils import (
    get_marketing_analytics_columns_with_conversion_goals, get_source_map_field,
    get_marketing_config_value, ConversionGoalProcessor, add_conversion_goal_property_filters,
    get_global_property_conditions
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

    def _get_marketing_source_adapters(self):
        """Get marketing source adapters using the new adapter architecture"""
        try:
            factory = MarketingSourceFactory(team=self.team)
            adapters = factory.create_adapters()
            valid_adapters = factory.get_valid_adapters(adapters)
            
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
                global_filters=self._get_global_property_conditions(),
                base_currency=getattr(self.team, 'primary_currency', DEFAULT_CURRENCY)
            )
            
            # Build the union query string using the factory
            factory = MarketingSourceFactory(team=self.team)
            union_query_string = factory.build_union_query(adapters, context)
            
            # Build the final query with ordering and pagination
            final_query_string = self._build_final_query_string(union_query_string)
            print(parse_select(final_query_string))
            print(final_query_string)
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
        filtered_conversion_goals = conversion_goals
        
        return MarketingAnalyticsTableQueryResponse(
            results=results,
            columns=get_marketing_analytics_columns_with_conversion_goals(filtered_conversion_goals),
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
        conversion_goal_ctes = self._generate_conversion_goal_ctes(conversion_goals)
        if conversion_goal_ctes:
            with_clause += f", {conversion_goal_ctes}"
        
        # Build ORDER BY clause
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
        
        order_by_clause = "ORDER BY " + ", ".join(order_by_parts) if order_by_parts else ""
        
        # Calculate limit and offset
        limit = self.query.limit or DEFAULT_LIMIT
        offset = self.query.offset or 0
        actual_limit = limit + PAGINATION_EXTRA  # Request one extra for pagination
        
        # Build conversion goal joins and selects
        conversion_joins = self._generate_conversion_goal_joins(conversion_goals)
        conversion_columns = self._generate_conversion_goal_selects(conversion_goals)
        
        # Build final SELECT
        base_columns = f"""    cc.campaign_name as "Campaign",
    cc.source_name as "Source",
    round(cc.total_cost, 2) as "Total Cost",
    round(cc.total_clicks, 0) as "Total Clicks", 
    round(cc.total_impressions, 0) as "Total Impressions",
    round(cc.total_cost / nullif(cc.total_clicks, 0), 2) as "Cost per Click",
    round(cc.total_clicks / nullif(cc.total_impressions, 0) * 100, 2) as "CTR\""""
        
        all_columns = base_columns
        if conversion_columns:
            all_columns += f",\n{conversion_columns}"
        
        final_query = f"""
{with_clause}
SELECT 
{all_columns}
FROM campaign_costs cc
{conversion_joins}
{order_by_clause}
LIMIT {actual_limit}
OFFSET {offset}
        """.strip()
        
        return final_query

    def _generate_conversion_goal_ctes(self, conversion_goals: list) -> str:
        """Generate CTEs for conversion goals with proper property filtering"""
        if not conversion_goals:
            return ""
        
        ctes = []
        for index, conversion_goal in enumerate(conversion_goals):
            # Create processor for this conversion goal
            processor = ConversionGoalProcessor(
                goal=conversion_goal,
                index=index,
                team=self.team,
                query_date_range=self.query_date_range
            )
            
            # Get all required components using the processor
            cte_name = processor.get_cte_name()
            table = processor.get_table_name()
            select_field = processor.get_select_field()
            utm_campaign_expr, utm_source_expr = processor.get_utm_expressions()
            
            # Build WHERE conditions
            where_conditions = processor.get_base_where_conditions()
            
            # Apply conversion goal specific property filters
            where_conditions = self._add_conversion_goal_property_filters(where_conditions, conversion_goal)
            
            # Add date range and global filters using helper
            date_field = processor.get_date_field()
            additional_conditions = self._build_where_conditions(
                include_date_range=True,
                include_global_filters=True,
                date_field=date_field,
                use_date_not_datetime=True  # Conversion goals use toDate instead of toDateTime
            )
            where_conditions.extend(additional_conditions)
            
            # Build the CTE query - simplified for performance
            cte_query = f"""
{cte_name} AS (
    SELECT 
        coalesce({utm_campaign_expr}, '{UNKNOWN_CAMPAIGN}') as campaign_name,
        coalesce({utm_source_expr}, '{UNKNOWN_SOURCE}') as source_name,
        {select_field} as conversion_{index}
    FROM {table}
    WHERE {' AND '.join(where_conditions)}
    GROUP BY campaign_name, source_name
)"""
            
            ctes.append(cte_query.strip())
        
        return ",\n".join(ctes)

    def _generate_conversion_goal_joins(self, conversion_goals: list) -> str:
        """Generate JOIN clauses for conversion goals"""
        if not conversion_goals:
            return ""
        
        joins = []
        for index, conversion_goal in enumerate(conversion_goals):
            processor = ConversionGoalProcessor(
                goal=conversion_goal, index=index, team=self.team, query_date_range=self.query_date_range
            )
            cte_name = processor.get_cte_name()
            join = f"""
LEFT JOIN {cte_name} cg_{index} ON cc.campaign_name = cg_{index}.campaign_name 
    AND cc.source_name = cg_{index}.source_name"""
            joins.append(join.strip())
        
        return "\n".join(joins)

    def _generate_conversion_goal_selects(self, conversion_goals: list) -> str:
        """Generate SELECT columns for conversion goals"""
        if not conversion_goals:
            return ""
        
        selects = []
        for index, conversion_goal in enumerate(conversion_goals):
            goal_name = getattr(conversion_goal, 'conversion_goal_name', f'Goal {index + 1}')
            
            # Add conversion count column
            selects.append(f'    cg_{index}.conversion_{index} as "{goal_name}"')
            
            # Add cost per conversion column
            selects.append(f'    round(cc.total_cost / nullif(cg_{index}.conversion_{index}, 0), 2) as "Cost per {goal_name}"')
        
        return ",\n".join(selects)

    def _convert_team_conversion_goals_to_objects(self, team_conversion_goals):
        """Convert team conversion goals from dict format to ConversionGoalFilter objects"""
        converted_goals = []
        
        for goal in team_conversion_goals:
            try:
                # Handle both dict and object formats
                if hasattr(goal, 'get'):
                    goal_dict = dict(goal) if hasattr(goal, 'items') else goal
                elif hasattr(goal, '__dict__'):
                    goal_dict = goal.__dict__
                else:
                    goal_dict = goal
                
                # Determine the correct ConversionGoalFilter type based on kind
                kind = goal_dict.get('kind', 'EventsNode')
                # Clean up the goal_dict for each schema type
                cleaned_goal_dict = goal_dict.copy()
                
                if kind == 'EventsNode':
                    # EventsNode doesn't need special field mapping
                    converted_goal = ConversionGoalFilter1(**cleaned_goal_dict)
                elif kind == 'ActionsNode':
                    # ActionsNode doesn't allow 'event' field - remove it
                    if 'event' in cleaned_goal_dict:
                        del cleaned_goal_dict['event']
                    converted_goal = ConversionGoalFilter2(**cleaned_goal_dict)
                elif kind == 'DataWarehouseNode':
                    # DataWarehouseNode doesn't allow 'event' field - remove it
                    if 'event' in cleaned_goal_dict:
                        del cleaned_goal_dict['event']

                    # ConversionGoalFilter3 expects both id_field and distinct_id_field
                    if 'distinct_id_field' in cleaned_goal_dict and 'id_field' not in cleaned_goal_dict:
                        cleaned_goal_dict['id_field'] = cleaned_goal_dict['distinct_id_field']
                        # Keep distinct_id_field as it's also required
                    
                    converted_goal = ConversionGoalFilter3(**cleaned_goal_dict)
                else:
                    # Default to EventsNode
                    converted_goal = ConversionGoalFilter1(**cleaned_goal_dict)
                
                converted_goals.append(converted_goal)
                
            except Exception as e:
                logger.error("Error converting team conversion goal", error=str(e), goal=str(goal), extra={
                    "team_id": self.team.pk
                })
                continue
        
        return converted_goals

    def _get_team_conversion_goals(self):
        """Get conversion goals from team marketing analytics config and convert to proper objects"""
        try:
            from posthog.models import Team
            team = Team.objects.get(pk=self.team.pk)
            marketing_config = getattr(team, 'marketing_analytics_config', None)
            
            team_conversion_goals = []
            if marketing_config:
                team_conversion_goals = self._get_marketing_config_value(marketing_config, 'conversion_goals', [])
            
            # Convert to proper ConversionGoalFilter objects
            converted_goals = self._convert_team_conversion_goals_to_objects(team_conversion_goals)

            return converted_goals
            
        except Exception as e:
            logger.error("Error getting team conversion goals", error=str(e), extra={
                "team_id": self.team.pk
            })
            return []

    def _get_source_map_field(self, source_map, field_name, fallback=None):
        """Helper to safely get field from source_map regardless of type"""
        return get_source_map_field(source_map, field_name, fallback)

    def _get_marketing_config_value(self, config, key, default=None):
        """Safely extract value from marketing config regardless of type"""
        return get_marketing_config_value(config, key, default)

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
            conditions.extend(self._get_global_property_conditions())
        
        return conditions

    def _get_global_property_conditions(self):
        """Extract global property filter conditions"""
        return get_global_property_conditions(self.query, self.team)

    def _add_conversion_goal_property_filters(self, conditions, conversion_goal):
        """Add conversion goal specific property filters to conditions"""
        return add_conversion_goal_property_filters(conditions, conversion_goal, self.team)




