from dataclasses import dataclass
from typing import Union
import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr, action_to_expr
from posthog.models import Action, Team
from posthog.schema import (
    BaseMathType,
    ConversionGoalFilter1,
    ConversionGoalFilter2,
    ConversionGoalFilter3,
    DateRange,
    MarketingAnalyticsHelperForColumnNames,
    PropertyMathType,
)
from .adapters.base import MarketingSourceAdapter
from .constants import (
    CAMPAIGN_COST_CTE_NAME,
    CONVERSION_GOAL_PREFIX,
    CONVERSION_GOAL_PREFIX_ABBREVIATION,
    DECIMAL_PRECISION,
    TOTAL_COST_FIELD,
    ORGANIC_CAMPAIGN,
    ORGANIC_SOURCE,
)

logger = structlog.get_logger(__name__)


@dataclass
class ConversionGoalProcessor:
    """Handles conversion goal processing logic"""

    goal: Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3]
    index: int
    team: Team
    query_date_range: DateRange | None
    use_temporal_attribution: bool = True  # For now it's always true, but might be configurable by the user
    utm_pageview_only: bool = (
        True  # Optimization: only search pageviews for UTM data, but might be configurable by the user
    )
    attribution_window_days: int = 3000  # Added for the new attribution window logic

    def get_cte_name(self):
        """Generate CTE name for conversion goal"""
        return self.goal.conversion_goal_id

    def get_table_name(self):
        """Get table name for conversion goal"""
        kind = self.goal.kind

        if kind == "EventsNode":
            return "events"
        elif kind == "ActionsNode":
            return "events"
        elif kind == "DataWarehouseNode" and isinstance(self.goal, ConversionGoalFilter3):
            return self.goal.table_name
        else:
            return "events"

    def get_utm_expressions(self) -> tuple[ast.Expr, ast.Expr]:
        """Get UTM campaign and source expressions based on node kind"""

        utm_campaign_field = self.goal.schema_map.get("utm_campaign_name", "utm_campaign")
        utm_source_field = self.goal.schema_map.get("utm_source_name", "utm_source")

        if self.goal.kind == "EventsNode" or self.goal.kind == "ActionsNode":
            # For events: events.properties.utm_campaign, events.properties.utm_source
            utm_campaign_expr = ast.Field(chain=["events", "properties", utm_campaign_field])
            utm_source_expr = ast.Field(chain=["events", "properties", utm_source_field])
        else:
            # For data warehouse: direct field access
            utm_campaign_expr = ast.Field(chain=[utm_campaign_field])
            utm_source_expr = ast.Field(chain=[utm_source_field])

        return utm_campaign_expr, utm_source_expr

    def get_select_field(self) -> ast.Expr:
        """Get the select field based on math type and node kind"""
        math_type = self.goal.math
        # Handle different math types
        if math_type in [BaseMathType.DAU, "dau"]:
            if self.goal.kind == "EventsNode" or self.goal.kind == "ActionsNode":
                # uniq(events.distinct_id)
                return ast.Call(name="uniq", args=[ast.Field(chain=["events", "distinct_id"])])
            elif self.goal.kind == "DataWarehouseNode":
                distinct_id_field = self.goal.schema_map.get("distinct_id_field", "distinct_id")
                return ast.Call(name="uniq", args=[ast.Field(chain=[distinct_id_field])])
            else:
                return ast.Call(name="uniq", args=[ast.Field(chain=["events", "distinct_id"])])
        elif math_type == "sum" or str(math_type).endswith("_sum") or math_type == PropertyMathType.SUM:
            math_property = self.goal.math_property
            if not math_property:
                return ast.Constant(value=0)
            else:
                if self.goal.kind == "EventsNode" or self.goal.kind == "ActionsNode":
                    # round(sum(toFloat(properties.math_property)), DECIMAL_PRECISION)
                    property_field = ast.Field(chain=["events", "properties", math_property])
                    to_float = ast.Call(name="toFloat", args=[property_field])
                    sum_expr = ast.Call(name="sum", args=[to_float])
                    return ast.Call(name="round", args=[sum_expr, ast.Constant(value=DECIMAL_PRECISION)])
                elif self.goal.kind == "DataWarehouseNode":
                    # round(sum(toFloat(math_property)), DECIMAL_PRECISION)
                    to_float = ast.Call(name="toFloat", args=[ast.Field(chain=[math_property])])
                    sum_expr = ast.Call(name="sum", args=[to_float])
                    return ast.Call(name="round", args=[sum_expr, ast.Constant(value=DECIMAL_PRECISION)])
                else:
                    # Same as events node
                    property_field = ast.Field(chain=["events", "properties", math_property])
                    to_float = ast.Call(name="toFloat", args=[property_field])
                    sum_expr = ast.Call(name="sum", args=[to_float])
                    return ast.Call(name="round", args=[sum_expr, ast.Constant(value=DECIMAL_PRECISION)])
        else:
            # count(*)
            return ast.Call(name="count", args=[ast.Constant(value="*")])

    def get_base_where_conditions(self) -> list[ast.Expr]:
        """Get base WHERE conditions for the conversion goal"""
        conditions: list[ast.Expr] = []

        # Add event filter for EventsNode
        if self.goal.kind == "EventsNode":
            event_name = self.goal.event
            if event_name:
                # events.event = 'event_name'
                event_condition = ast.CompareOperation(
                    left=ast.Field(chain=["events", "event"]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value=event_name),
                )
                conditions.append(event_condition)
        elif self.goal.kind == "ActionsNode":
            # Handle ActionsNode by converting action to HogQL expression
            action_id = self.goal.id
            if action_id:
                action = Action.objects.get(pk=int(action_id), team__project_id=self.team.project_id)
                # action_to_expr handles all the action step logic internally
                action_expr = action_to_expr(action)
                conditions.append(action_expr)

        elif self.goal.kind == "DataWarehouseNode":
            pass

        return conditions

    def get_date_field(self):
        """Get the appropriate date field for the conversion goal"""
        if self.goal.kind == "DataWarehouseNode":
            return self.goal.schema_map.get("timestamp_field", "timestamp")
        else:
            return "events.timestamp"

    def generate_cte_query(self, additional_conditions: list[ast.Expr]) -> ast.SelectQuery:
        """
        MAIN ENTRY POINT: Generate the complete CTE query for this conversion goal

        HYBRID ATTRIBUTION FLOW FOR EVENTS/ACTIONS:
        ┌─────────────────────────────────────────────────────────────────────────────┐
        │ STEP 1: generate_person_utm_subquery()                                     │
        │ → Get each person's most recent UTM data (fallback for events w/o UTM)     │
        └─────────────────────────────────────────────────────────────────────────────┘
                                            ↓
        ┌─────────────────────────────────────────────────────────────────────────────┐
        │ STEP 2: generate_conversion_data_with_utm_subquery()                        │
        │ → Get conversion events + their direct UTM data (may be NULL)              │
        └─────────────────────────────────────────────────────────────────────────────┘
                                            ↓
        ┌─────────────────────────────────────────────────────────────────────────────┐
        │ STEP 3: generate_person_level_cte_query()                                  │
        │ → JOIN the above + use coalesce(event_utm, person_utm, 'organic')          │
        │ → Final output: campaign_name, source_name, conversion_count               │
        └─────────────────────────────────────────────────────────────────────────────┘

        RESULT: Each conversion is attributed to:
        1. Event UTM (if conversion event has UTM data)
        2. Person UTM (if person has UTM history within date range but event doesn't)
        3. Organic (if no UTM data found within the query date range)
        """

        if self.goal.kind == "EventsNode" or self.goal.kind == "ActionsNode":
            # For Events/Actions: Use hybrid event/person-level UTM attribution
            return self.generate_person_level_cte_query(additional_conditions, self.use_temporal_attribution)
        else:
            # For DataWarehouse: Use direct field access (existing behavior)
            return self.generate_direct_cte_query(additional_conditions)

    def generate_person_level_cte_query(
        self, additional_conditions: list[ast.Expr], use_temporal_attribution: bool = False
    ) -> ast.SelectQuery:
        """
        Generate main CTE query - using funnel-based approach for proper attribution window support
        
        Uses aggregate_funnel_array to create a funnel:
        - Step 0: UTM pageview (with complete UTM data)
        - Step 1: Conversion event
        - Attribution window: self.attribution_window_days converted to seconds
        """
        if self.attribution_window_days > 0:
            return self.generate_funnel_based_cte_query(additional_conditions)
        else:
            # Fallback to direct approach if no attribution window specified
            return self.generate_direct_cte_query(additional_conditions)

    def generate_funnel_based_cte_query(self, additional_conditions: list[ast.Expr]) -> ast.SelectQuery:
        """
        Generate CTE query using optimized array-based approach
        
        This replaces the funnel-based logic with a high-performance single-pass query that:
        - Scans events table only once per person
        - Uses arrays to store conversion and UTM data
        - Applies attribution window logic in-memory using array functions
        - Handles both direct attribution (conversions with UTM) and fallback attribution
        """
        # Convert attribution window days to seconds
        attribution_window_seconds = self.attribution_window_days * 24 * 60 * 60
        
        # Get event name for the conversion goal
        conversion_event = self.goal.event if self.goal.kind == "EventsNode" else "purchase"
        
        # Build conditions string for the WHERE clause
        additional_conditions_str = self.build_additional_conditions_string(additional_conditions)
        
        # Get aggregation field based on math type
        aggregation_field = self.get_array_based_aggregation_field()
        
        # Build the optimized array-based query
        array_query = f"""
        SELECT
            if(notEmpty(campaign_name), campaign_name, '{ORGANIC_CAMPAIGN}') AS {MarketingSourceAdapter.campaign_name_field},
            if(notEmpty(source_name), source_name, '{ORGANIC_SOURCE}') AS {MarketingSourceAdapter.source_name_field},
            {aggregation_field} AS {CONVERSION_GOAL_PREFIX + str(self.index)}
        FROM (
            SELECT 
                person_id,
                -- Extract attribution for each conversion (handle campaign and source independently)
                if(
                    -- Direct attribution: conversion has its own campaign
                    notEmpty(conversion_campaign),
                    conversion_campaign,
                    -- Fallback attribution: find most recent UTM pageview within window
                    if(
                        notEmpty(fallback_campaign),
                        fallback_campaign,
                        ''
                    )
                ) as campaign_name,
                if(
                    -- Direct attribution: conversion has its own source
                    notEmpty(conversion_source),
                    conversion_source,
                    -- Fallback attribution: find most recent UTM pageview within window
                    if(
                        notEmpty(fallback_source),
                        fallback_source,
                        ''
                    )
                ) as source_name,
                {self.get_conversion_value_field()} as conversion_value
            FROM (
                SELECT 
                    person_id,
                    conversion_timestamps[i] as conversion_time,
                    conversion_math_values[i] as conversion_math_value,
                    conversion_campaigns[i] as conversion_campaign,
                    conversion_sources[i] as conversion_source,
                    
                    -- Find most recent UTM pageview within attribution window before conversion
                    arrayElement(
                        arraySort(x -> -x,  -- Sort timestamps DESC (most recent first)
                            arrayFilter(
                                x -> x <= conversion_timestamps[i]  -- Before conversion
                                     AND x >= conversion_timestamps[i] - {attribution_window_seconds},  -- Within attribution window
                                utm_timestamps
                            )
                        ), 1
                    ) as last_utm_timestamp,
                    
                    -- Get campaign/source for that timestamp
                    if(last_utm_timestamp IS NOT NULL,
                        utm_campaigns[indexOf(utm_timestamps, last_utm_timestamp)],
                        ''
                    ) as fallback_campaign,
                    
                    if(last_utm_timestamp IS NOT NULL,
                        utm_sources[indexOf(utm_timestamps, last_utm_timestamp)],
                        ''
                    ) as fallback_source
                FROM (
                    -- Single pass: collect all events per person using separate arrays for each data type
                    SELECT 
                        events.person_id,
                        -- Conversion data - separate arrays for each field
                        arrayFilter(x -> x > 0, groupArray(
                            if(events.event = '{conversion_event}', toUnixTimestamp(events.timestamp), 0)
                        )) as conversion_timestamps,
                        
                        arrayFilter(x -> x IS NOT NULL, groupArray(
                            if(events.event = '{conversion_event}', {self.get_conversion_math_property_expression()}, NULL)
                        )) as conversion_math_values,
                        
                        arrayFilter(x -> x IS NOT NULL, groupArray(
                            if(events.event = '{conversion_event}',
                                if(
                                    equals(events.properties.utm_campaign, NULL) OR equals(events.properties.utm_campaign, ''),
                                    '',  -- No campaign on conversion event
                                    toString(ifNull(events.properties.utm_campaign, ''))  -- Campaign present on conversion
                                ),
                                NULL
                            )
                        )) as conversion_campaigns,
                        
                        arrayFilter(x -> x IS NOT NULL, groupArray(
                            if(events.event = '{conversion_event}',
                                if(
                                    equals(events.properties.utm_source, NULL) OR equals(events.properties.utm_source, ''),
                                    '',  -- No source on conversion event
                                    toString(ifNull(events.properties.utm_source, ''))  -- Source present on conversion
                                ),
                                NULL
                            )
                        )) as conversion_sources,
                        
                        -- UTM pageview data - separate arrays
                        arrayFilter(x -> x > 0, groupArray(
                            if(events.event = '$pageview' 
                               AND notEmpty(toString(ifNull(events.properties.utm_campaign, ''))) 
                               AND notEmpty(toString(ifNull(events.properties.utm_source, ''))),
                                toUnixTimestamp(events.timestamp),
                                0
                            )
                        )) as utm_timestamps,
                        
                        arrayFilter(x -> notEmpty(x), groupArray(
                            if(events.event = '$pageview' 
                               AND notEmpty(toString(ifNull(events.properties.utm_campaign, ''))) 
                               AND notEmpty(toString(ifNull(events.properties.utm_source, ''))),
                                toString(ifNull(events.properties.utm_campaign, '')),
                                ''
                            )
                        )) as utm_campaigns,
                        
                        arrayFilter(x -> notEmpty(x), groupArray(
                            if(events.event = '$pageview' 
                               AND notEmpty(toString(ifNull(events.properties.utm_campaign, ''))) 
                               AND notEmpty(toString(ifNull(events.properties.utm_source, ''))),
                                toString(ifNull(events.properties.utm_source, '')),
                                ''
                            )
                        )) as utm_sources
                    FROM events
                    WHERE (events.event = '$pageview' OR events.event = '{conversion_event}')
                        {additional_conditions_str}
                    GROUP BY events.person_id
                    HAVING length(conversion_timestamps) > 0  -- Only people who converted
                ) 
                -- Create array indices to iterate through conversions
                ARRAY JOIN arrayEnumerate(conversion_timestamps) as i
            )
        ) as attributed_conversions
        GROUP BY {MarketingSourceAdapter.campaign_name_field}, {MarketingSourceAdapter.source_name_field}
        """
        
        # Parse the HogQL query string into AST
        return parse_select(array_query)

    def get_array_based_aggregation_field(self) -> str:
        """Get the aggregation field for the array-based query based on math type"""
        math_type = self.goal.math
        if math_type in [BaseMathType.DAU, "dau"]:
            return "uniq(person_id)"
        elif math_type == "sum" or str(math_type).endswith("_sum"):
            return "sum(conversion_value)"
        else:
            return "count() as conversion_count"

    def get_conversion_math_property_expression(self) -> str:
        """Get the math property expression for conversions based on math type"""
        math_type = self.goal.math
        math_property = getattr(self.goal, 'math_property', None)
        
        if (math_type == "sum" or str(math_type).endswith("_sum")) and math_property:
            # Use string '0' as fallback to match the string type from property extraction
            return f"toFloat(ifNull(events.properties.{math_property}, '0'))"
        else:
            return "1"  # For count-based or DAU, just use 1

    def get_conversion_value_field(self) -> str:
        """Get the conversion value field based on math type"""
        math_type = self.goal.math
        if math_type in [BaseMathType.DAU, "dau"]:
            return "person_id"  # For DAU, we need person_id to count unique users
        elif math_type == "sum" or str(math_type).endswith("_sum"):
            return "toFloat(conversion_math_value)"
        else:
            return "1"  # For count-based, each conversion = 1

    def build_additional_conditions_string(self, additional_conditions: list[ast.Expr]) -> str:
        """Convert additional conditions to HogQL string with proper attribution window handling"""
        if not additional_conditions:
            return ""
        
        conditions_parts = []
        
        # Add date range with proper attribution window logic
        if self.query_date_range:
            start_date = self.query_date_range.date_from or "2020-01-01"
            end_date = self.query_date_range.date_to or "2030-01-01"
            
            # For conversion events: respect query date range exactly
            conversion_event = self.goal.event if self.goal.kind == "EventsNode" else "purchase"
            conversion_date_filter = f"""AND (
                (events.event = '{conversion_event}' AND events.timestamp >= toDateTime('{start_date}') AND events.timestamp <= toDateTime('{end_date}'))
            """
            
            # For UTM pageviews: extend backwards by attribution window for proper attribution
            # Calculate the extended start date for UTM lookback
            attribution_window_seconds = self.attribution_window_days * 24 * 60 * 60
            utm_lookback_condition = f"""OR (
                events.event = '$pageview' 
                AND notEmpty(toString(ifNull(events.properties.utm_campaign, ''))) 
                AND notEmpty(toString(ifNull(events.properties.utm_source, '')))
                AND events.timestamp <= toDateTime('{end_date}')
                AND events.timestamp >= toDateTime('{start_date}') - INTERVAL {attribution_window_seconds} SECOND
            )"""
            
            # Combine the conditions
            combined_filter = conversion_date_filter + "\n                        " + utm_lookback_condition + "\n                        )"
            conditions_parts.append(combined_filter)
        
        return "\n                        ".join(conditions_parts)

    def generate_direct_cte_query(self, additional_conditions: list[ast.Expr]) -> ast.SelectQuery:
        """Generate CTE query with direct field access for DataWarehouse nodes"""

        # Get all required components
        table = self.get_table_name()
        select_field = self.get_select_field()
        utm_campaign_expr, utm_source_expr = self.get_utm_expressions()

        # Build WHERE conditions
        where_conditions = self.get_base_where_conditions()
        where_conditions = add_conversion_goal_property_filters(where_conditions, self.goal, self.team)
        where_conditions.extend(additional_conditions)

        # Build coalesce expressions for UTM fields with organic defaults
        campaign_coalesce = ast.Call(name="coalesce", args=[utm_campaign_expr, ast.Constant(value=ORGANIC_CAMPAIGN)])
        source_coalesce = ast.Call(name="coalesce", args=[utm_source_expr, ast.Constant(value=ORGANIC_SOURCE)])

        # Build SELECT columns
        select_columns: list[ast.Expr] = [
            ast.Alias(alias=MarketingSourceAdapter.campaign_name_field, expr=campaign_coalesce),
            ast.Alias(alias=MarketingSourceAdapter.source_name_field, expr=source_coalesce),
            ast.Alias(alias=CONVERSION_GOAL_PREFIX + str(self.index), expr=select_field),
        ]

        # Build FROM clause
        from_expr = ast.JoinExpr(table=ast.Field(chain=[table]))

        # Build WHERE clause - combine all conditions
        where_expr: ast.Expr | None = None
        if where_conditions:
            if len(where_conditions) == 1:
                where_expr = where_conditions[0]
            else:
                where_expr = ast.And(exprs=where_conditions)

        # Build GROUP BY
        group_by_exprs: list[ast.Expr] = [
            ast.Field(chain=[MarketingSourceAdapter.campaign_name_field]),
            ast.Field(chain=[MarketingSourceAdapter.source_name_field]),
        ]

        # Return complete SelectQuery
        return ast.SelectQuery(select=select_columns, select_from=from_expr, where=where_expr, group_by=group_by_exprs)

    def generate_cte_query_expr(self, additional_conditions: list[ast.Expr]) -> ast.Expr:
        """Generate the complete CTE query string for this conversion goal"""
        cte_name = self.get_cte_name()
        select_query = self.generate_cte_query(additional_conditions)

        cte_alias = ast.Alias(alias=cte_name, expr=select_query)
        return cte_alias

    def generate_join_clause(self) -> ast.JoinExpr:
        """Generate the JOIN clause for this conversion goal"""
        cte_name = self.get_cte_name()
        alias = CONVERSION_GOAL_PREFIX_ABBREVIATION + str(self.index)

        # Build join conditions: campaign_name = campaign_name AND source_name = source_name
        campaign_condition = ast.CompareOperation(
            left=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, MarketingSourceAdapter.campaign_name_field]),
            op=ast.CompareOperationOp.Eq,
            right=ast.Field(chain=[alias, MarketingSourceAdapter.campaign_name_field]),
        )

        source_condition = ast.CompareOperation(
            left=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, MarketingSourceAdapter.source_name_field]),
            op=ast.CompareOperationOp.Eq,
            right=ast.Field(chain=[alias, MarketingSourceAdapter.source_name_field]),
        )

        join_condition = ast.And(exprs=[campaign_condition, source_condition])
        join_constraint = ast.JoinConstraint(expr=join_condition, constraint_type="ON")

        return ast.JoinExpr(
            join_type="LEFT JOIN", table=ast.Field(chain=[cte_name]), alias=alias, constraint=join_constraint
        )

    def generate_select_columns(self) -> list[ast.Expr]:
        """Generate the SELECT columns for this conversion goal"""
        goal_name = self.goal.conversion_goal_name
        alias_prefix = CONVERSION_GOAL_PREFIX_ABBREVIATION + str(self.index)

        # First column: conversion goal value
        conversion_goal_field = ast.Field(chain=[alias_prefix, CONVERSION_GOAL_PREFIX + str(self.index)])
        conversion_goal_alias = ast.Alias(alias=goal_name, expr=conversion_goal_field)

        # Second column: Cost per conversion goal
        cost_field = ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_COST_FIELD])
        goal_field = ast.Field(chain=[alias_prefix, CONVERSION_GOAL_PREFIX + str(self.index)])

        # Build: nullif(goal_field, 0)
        nullif_expr = ast.Call(name="nullif", args=[goal_field, ast.Constant(value=0)])

        # Build: cost_field / nullif_expr
        division_expr = ast.ArithmeticOperation(left=cost_field, op=ast.ArithmeticOperationOp.Div, right=nullif_expr)

        # Build: round(division_expr, DECIMAL_PRECISION)
        round_expr = ast.Call(name="round", args=[division_expr, ast.Constant(value=DECIMAL_PRECISION)])

        cost_per_goal_alias = ast.Alias(
            alias=f"{MarketingAnalyticsHelperForColumnNames.COST_PER} {goal_name}", expr=round_expr
        )

        return [conversion_goal_alias, cost_per_goal_alias]




def add_conversion_goal_property_filters(
    conditions: list[ast.Expr],
    conversion_goal: ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3,
    team: Team,
) -> list[ast.Expr]:
    """Add conversion goal specific property filters to conditions"""
    conversion_goal_properties = conversion_goal.properties
    if conversion_goal_properties:
        try:
            property_expr = property_to_expr(conversion_goal_properties, team=team, scope="event")
            if property_expr:
                conditions.append(property_expr)
        except Exception as e:
            logger.exception("Error applying property filters to conversion goal", error=str(e))
    return conditions
