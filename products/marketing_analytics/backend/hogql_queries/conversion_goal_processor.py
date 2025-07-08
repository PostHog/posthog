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
        Generate CTE query using array-based approach with AST expressions
        
        This maintains the sophisticated array-based attribution logic but uses AST
        nodes instead of SQL strings, which automatically integrates with property filters.
        """
        # Get UTM expressions for schema mapping
        utm_campaign_expr, utm_source_expr = self.get_utm_expressions()
        
        # Get conversion event name
        conversion_event = self.goal.event if self.goal.kind == "EventsNode" else "purchase"
        
        # Build WHERE conditions (includes property filters automatically via AST)
        where_conditions = self.get_base_where_conditions()
        where_conditions = add_conversion_goal_property_filters(where_conditions, self.goal, self.team)
        where_conditions.extend(additional_conditions)
        
        # Convert attribution window days to seconds
        attribution_window_seconds = self.attribution_window_days * 24 * 60 * 60
        
        # Build the complex nested query structure using AST
        innermost_query = self.build_array_collection_subquery(conversion_event, where_conditions)
        array_join_query = self.build_array_join_subquery(innermost_query, attribution_window_seconds)
        attribution_query = self.build_attribution_logic_subquery(array_join_query)
        
        # Build final aggregation query
        return self.build_final_aggregation_query(attribution_query)
    
    def build_array_collection_subquery(self, conversion_event: str, where_conditions: list[ast.Expr]) -> ast.SelectQuery:
        """Build the innermost subquery that collects arrays of conversion and UTM data per person"""
        
        # Get UTM field names from schema mapping
        utm_campaign_field = self.goal.schema_map.get("utm_campaign_name", "utm_campaign")
        utm_source_field = self.goal.schema_map.get("utm_source_name", "utm_source")
        
        # Extract date conditions from additional conditions for the temporal attribution logic
        date_conditions = []
        non_date_conditions = []
        
        for condition in where_conditions:
            if self._is_date_condition(condition):
                date_conditions.append(condition)
            elif self._is_event_condition(condition, conversion_event):
                # Skip event conditions since we handle them explicitly in our logic
                continue
            else:
                non_date_conditions.append(condition)
        
        # Build the WHERE clause following the exact original working pattern:
        # AND(
        #   OR(events.event = '$pageview', events.event = 'conversion'),
        #   OR(
        #     AND(events.event = 'conversion', [all date conditions]),
        #     AND(events.event = '$pageview', [UTM conditions], [extended date conditions])
        #   )
        # )
        
        # Base event filter
        base_event_filter = ast.Or(exprs=[
            ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview")
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=conversion_event)
            )
        ])
        
        # Build event-specific conditions
        event_specific_conditions = []
        
        # Conversion event conditions: event = conversion + all original date conditions
        conversion_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=conversion_event)
            )
        ]
        
        # Add all date conditions to conversions (with proper toDateTime calls)
        for condition in date_conditions:
            if isinstance(condition, ast.CompareOperation):
                conversion_conditions.append(ast.CompareOperation(
                    left=ast.Field(chain=["events", "timestamp"]),
                    op=condition.op,
                    right=self._ensure_datetime_call(condition.right)
                ))
        
        event_specific_conditions.append(ast.And(exprs=conversion_conditions))
        
        # Pageview event conditions: event = pageview + UTM requirements + extended date conditions
        pageview_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview")
            ),
            # Must have utm_campaign
            ast.Call(name="notEmpty", args=[
                ast.Call(name="toString", args=[
                    ast.Call(name="ifNull", args=[
                        ast.Field(chain=["events", "properties", utm_campaign_field]),
                        ast.Constant(value="")
                    ])
                ])
            ]),
            # Must have utm_source  
            ast.Call(name="notEmpty", args=[
                ast.Call(name="toString", args=[
                    ast.Call(name="ifNull", args=[
                        ast.Field(chain=["events", "properties", utm_source_field]),
                        ast.Constant(value="")
                    ])
                ])
            ])
        ]
        
        # Add extended date conditions for pageviews (with attribution window)
        attribution_window_seconds = self.attribution_window_days * 24 * 60 * 60
        
        for condition in date_conditions:
            if isinstance(condition, ast.CompareOperation):
                if condition.op == ast.CompareOperationOp.GtEq:
                    # Extend start date backwards by attribution window
                    pageview_conditions.append(ast.CompareOperation(
                        left=ast.Field(chain=["events", "timestamp"]),
                        op=ast.CompareOperationOp.GtEq,
                        right=ast.ArithmeticOperation(
                            left=self._ensure_datetime_call(condition.right),
                            op=ast.ArithmeticOperationOp.Sub,
                            right=ast.Call(name="toIntervalSecond", args=[ast.Constant(value=attribution_window_seconds)])
                        )
                    ))
                elif condition.op == ast.CompareOperationOp.LtEq:
                    # Keep end date as-is for pageviews
                    pageview_conditions.append(ast.CompareOperation(
                        left=ast.Field(chain=["events", "timestamp"]),
                        op=ast.CompareOperationOp.LtEq,
                        right=self._ensure_datetime_call(condition.right)
                    ))
        
        event_specific_conditions.append(ast.And(exprs=pageview_conditions))
        
        # Build final WHERE clause: base_event_filter AND event_specific_conditions AND non_date_conditions
        where_parts = [
            base_event_filter,
            ast.Or(exprs=event_specific_conditions)
        ]
        where_parts.extend(non_date_conditions)
        
        final_where = ast.And(exprs=where_parts) if len(where_parts) > 1 else where_parts[0]
        
        # Build SELECT columns with array collection logic (keep existing)
        select_columns: list[ast.Expr] = [
            ast.Field(chain=["events", "person_id"]),
            
            # Conversion timestamps array
            ast.Alias(
                alias="conversion_timestamps",
                expr=ast.Call(name="arrayFilter", args=[
                    ast.Lambda(args=["x"], expr=ast.CompareOperation(
                        left=ast.Field(chain=["x"]),
                        op=ast.CompareOperationOp.Gt,
                        right=ast.Constant(value=0)
                    )),
                    ast.Call(name="groupArray", args=[
                        ast.Call(name="if", args=[
                            ast.CompareOperation(
                                left=ast.Field(chain=["events", "event"]),
                                op=ast.CompareOperationOp.Eq,
                                right=ast.Constant(value=conversion_event)
                            ),
                            ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])]),
                            ast.Constant(value=0)
                        ])
                    ])
                ])
            ),
            
            # Conversion math values array
            ast.Alias(
                alias="conversion_math_values",
                expr=ast.Call(name="arrayFilter", args=[
                    ast.Lambda(args=["x"], expr=ast.CompareOperation(
                        left=ast.Field(chain=["x"]),
                        op=ast.CompareOperationOp.NotEq,
                        right=ast.Constant(value=None)
                    )),
                    ast.Call(name="groupArray", args=[
                        ast.Call(name="if", args=[
                            ast.CompareOperation(
                                left=ast.Field(chain=["events", "event"]),
                                op=ast.CompareOperationOp.Eq,
                                right=ast.Constant(value=conversion_event)
                            ),
                            self.get_conversion_value_ast_expr(),
                            ast.Constant(value=None)
                        ])
                    ])
                ])
            ),
            
            # Conversion campaigns array
            self.build_conversion_utm_array("conversion_campaigns", conversion_event, utm_campaign_field),
            
            # Conversion sources array  
            self.build_conversion_utm_array("conversion_sources", conversion_event, utm_source_field),
            
            # UTM pageview arrays
            self.build_utm_pageview_array("utm_timestamps", utm_campaign_field, utm_source_field, "timestamp"),
            self.build_utm_pageview_array("utm_campaigns", utm_campaign_field, utm_source_field, utm_campaign_field),
            self.build_utm_pageview_array("utm_sources", utm_campaign_field, utm_source_field, utm_source_field),
        ]
        
        # Build FROM and WHERE
        from_expr = ast.JoinExpr(table=ast.Field(chain=["events"]))
        
        # Build GROUP BY
        group_by_exprs = [ast.Field(chain=["events", "person_id"])]
        
        # Build HAVING: only people who converted
        having_expr = ast.CompareOperation(
            left=ast.Call(name="length", args=[ast.Field(chain=["conversion_timestamps"])]),
            op=ast.CompareOperationOp.Gt,
            right=ast.Constant(value=0)
        )
        
        return ast.SelectQuery(
            select=select_columns,
            select_from=from_expr,
            where=final_where,
            group_by=group_by_exprs,
            having=having_expr
        )
    
    def _get_pageview_date_conditions(self, condition: ast.Expr) -> list[ast.Expr]:
        """Get both upper and lower bound date conditions for pageviews"""
        if not isinstance(condition, ast.CompareOperation):
            return []
            
        conditions = []
        
        # Convert attribution window days to seconds
        attribution_window_seconds = self.attribution_window_days * 24 * 60 * 60
        
        # Handle >= start_date: extend backwards by attribution window
        if (condition.op == ast.CompareOperationOp.GtEq and 
            isinstance(condition.left, ast.Field) and 
            'timestamp' in condition.left.chain):
            
            # Create: greaterOrEquals(events.timestamp, minus(toDateTime(start_date), toIntervalSecond(attribution_window)))
            extended_start = ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.ArithmeticOperation(
                    left=self._ensure_datetime_call(condition.right),
                    op=ast.ArithmeticOperationOp.Sub,
                    right=ast.Call(name="toIntervalSecond", args=[ast.Constant(value=attribution_window_seconds)])
                )
            )
            conditions.append(extended_start)
            
        # Handle <= end_date: keep as upper bound for pageviews  
        elif (condition.op == ast.CompareOperationOp.LtEq and 
              isinstance(condition.left, ast.Field) and 
              'timestamp' in condition.left.chain):
            
            # Create: lessOrEquals(events.timestamp, toDateTime(end_date))
            upper_bound = ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.LtEq,
                right=self._ensure_datetime_call(condition.right)
            )
            conditions.append(upper_bound)
            
        return conditions
    
    def _ensure_datetime_call(self, date_expr: ast.Expr) -> ast.Expr:
        """Ensure date expression uses toDateTime instead of toDate"""
        if isinstance(date_expr, ast.Call) and date_expr.name == "toDate":
            # Convert toDate to toDateTime
            return ast.Call(name="toDateTime", args=date_expr.args)
        return date_expr
    
    def _extend_date_condition_for_attribution_window(self, condition: ast.Expr) -> ast.Expr | None:
        """Extend a date condition to include attribution window for pageviews"""
        if not isinstance(condition, ast.CompareOperation):
            return None
            
        # Convert attribution window days to seconds
        attribution_window_seconds = self.attribution_window_days * 24 * 60 * 60
        
        # Look for >= start_date conditions and extend them backwards
        if (condition.op == ast.CompareOperationOp.GtEq and 
            isinstance(condition.left, ast.Field) and 
            'timestamp' in condition.left.chain):
            
            # Create: greaterOrEquals(events.timestamp, minus(start_date, attribution_window))
            extended_start = ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.ArithmeticOperation(
                    left=condition.right,  # Original start date
                    op=ast.ArithmeticOperationOp.Sub,
                    right=ast.Call(name="toIntervalSecond", args=[ast.Constant(value=attribution_window_seconds)])
                )
            )
            return extended_start
            
        # For <= end_date conditions, keep them as-is for pageviews
        elif (condition.op == ast.CompareOperationOp.LtEq and 
              isinstance(condition.left, ast.Field) and 
              'timestamp' in condition.left.chain):
            return condition
            
        return None
    
    def _is_date_condition(self, condition: ast.Expr) -> bool:
        """Check if a condition is related to date/timestamp filtering"""
        def _check_field_for_timestamp(expr: ast.Expr) -> bool:
            if isinstance(expr, ast.Field):
                # Check if field chain contains 'timestamp'
                return 'timestamp' in expr.chain
            elif isinstance(expr, ast.CompareOperation):
                return _check_field_for_timestamp(expr.left) or _check_field_for_timestamp(expr.right)
            elif isinstance(expr, ast.Call):
                return any(_check_field_for_timestamp(arg) for arg in expr.args)
            return False
        
        return _check_field_for_timestamp(condition)
    
    def _is_event_condition(self, condition: ast.Expr, conversion_event: str) -> bool:
        """Check if a condition is related to event filtering"""
        if isinstance(condition, ast.CompareOperation):
            # Check if it's filtering events.event
            if (isinstance(condition.left, ast.Field) and 
                condition.left.chain == ["events", "event"] and
                condition.op == ast.CompareOperationOp.Eq and
                isinstance(condition.right, ast.Constant)):
                
                # Skip if it's filtering for our conversion event or pageview
                event_value = condition.right.value
                return event_value == conversion_event or event_value == "$pageview"
        return False
    
    def build_conversion_utm_array(self, alias: str, conversion_event: str, utm_field: str) -> ast.Alias:
        """Build array for conversion event UTM data (campaign or source)"""
        return ast.Alias(
            alias=alias,
            expr=ast.Call(name="arrayFilter", args=[
                ast.Lambda(args=["x"], expr=ast.CompareOperation(
                    left=ast.Field(chain=["x"]),
                    op=ast.CompareOperationOp.NotEq,
                    right=ast.Constant(value=None)
                )),
                ast.Call(name="groupArray", args=[
                    ast.Call(name="if", args=[
                        ast.CompareOperation(
                            left=ast.Field(chain=["events", "event"]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Constant(value=conversion_event)
                        ),
                        ast.Call(name="if", args=[
                            ast.Or(exprs=[
                                ast.Call(name="equals", args=[
                                    ast.Field(chain=["events", "properties", utm_field]),
                                    ast.Constant(value=None)
                                ]),
                                ast.Call(name="equals", args=[
                                    ast.Field(chain=["events", "properties", utm_field]),
                                    ast.Constant(value="")
                                ])
                            ]),
                            ast.Constant(value=""),  # No UTM on conversion event
                            ast.Call(name="toString", args=[
                                ast.Call(name="ifNull", args=[
                                    ast.Field(chain=["events", "properties", utm_field]),
                                    ast.Constant(value="")
                                ])
                            ])  # UTM present on conversion
                        ]),
                        ast.Constant(value=None)
                    ])
                ])
            ])
        )
    
    def build_utm_pageview_array(self, alias: str, utm_campaign_field: str, utm_source_field: str, return_field: str) -> ast.Alias:
        """Build array for UTM pageview data"""
        
        # Build condition for pageviews with complete UTM data
        pageview_with_utm = ast.And(exprs=[
            ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview")
            ),
            ast.Call(name="notEmpty", args=[
                ast.Call(name="toString", args=[
                    ast.Call(name="ifNull", args=[
                        ast.Field(chain=["events", "properties", utm_campaign_field]),
                        ast.Constant(value="")
                    ])
                ])
            ]),
            ast.Call(name="notEmpty", args=[
                ast.Call(name="toString", args=[
                    ast.Call(name="ifNull", args=[
                        ast.Field(chain=["events", "properties", utm_source_field]),
                        ast.Constant(value="")
                    ])
                ])
            ])
        ])
        
        # Determine what to return and how to filter based on field type
        if return_field == "timestamp":
            return_expr = ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])])
            false_value = ast.Constant(value=0)  # Use 0 for integer timestamps
            # For integers, filter using x > 0
            filter_expr = ast.CompareOperation(
                left=ast.Field(chain=["x"]),
                op=ast.CompareOperationOp.Gt,
                right=ast.Constant(value=0)
            )
        else:
            return_expr = ast.Call(name="toString", args=[
                ast.Call(name="ifNull", args=[
                    ast.Field(chain=["events", "properties", return_field]),
                    ast.Constant(value="")
                ])
            ])
            false_value = ast.Constant(value="")  # Use '' for string fields
            # For strings, filter using notEmpty(x)
            filter_expr = ast.Call(name="notEmpty", args=[ast.Field(chain=["x"])])
        
        return ast.Alias(
            alias=alias,
            expr=ast.Call(name="arrayFilter", args=[
                ast.Lambda(args=["x"], expr=filter_expr),
                ast.Call(name="groupArray", args=[
                    ast.Call(name="if", args=[
                        pageview_with_utm,
                        return_expr,
                        false_value
                    ])
                ])
            ])
        )
    
    def build_array_join_subquery(self, inner_query: ast.SelectQuery, attribution_window_seconds: int) -> ast.SelectQuery:
        """Build the middle subquery that does ARRAY JOIN and attribution window logic"""
        
        select_columns: list[ast.Expr] = [
            ast.Field(chain=["person_id"]),
            ast.Alias(alias="conversion_time", expr=ast.ArrayAccess(
                array=ast.Field(chain=["conversion_timestamps"]),
                property=ast.Field(chain=["i"])
            )),
            ast.Alias(alias="conversion_math_value", expr=ast.ArrayAccess(
                array=ast.Field(chain=["conversion_math_values"]),
                property=ast.Field(chain=["i"])
            )),
            ast.Alias(alias="conversion_campaign", expr=ast.ArrayAccess(
                array=ast.Field(chain=["conversion_campaigns"]),
                property=ast.Field(chain=["i"])
            )),
            ast.Alias(alias="conversion_source", expr=ast.ArrayAccess(
                array=ast.Field(chain=["conversion_sources"]),
                property=ast.Field(chain=["i"])
            )),
            
            # Find most recent UTM pageview within attribution window
            ast.Alias(
                alias="last_utm_timestamp",
                expr=ast.Call(name="arrayElement", args=[
                    ast.Call(name="arraySort", args=[
                        ast.Lambda(args=["x"], expr=ast.ArithmeticOperation(
                            left=ast.Constant(value=0),
                            op=ast.ArithmeticOperationOp.Sub,
                            right=ast.Field(chain=["x"])
                        )),  # Sort DESC (most recent first)
                        ast.Call(name="arrayFilter", args=[
                            ast.Lambda(args=["x"], expr=ast.And(exprs=[
                                ast.CompareOperation(
                                    left=ast.Field(chain=["x"]),
                                    op=ast.CompareOperationOp.LtEq,
                                    right=ast.ArrayAccess(
                                        array=ast.Field(chain=["conversion_timestamps"]),
                                        property=ast.Field(chain=["i"])
                                    )
                                ),
                                ast.CompareOperation(
                                    left=ast.Field(chain=["x"]),
                                    op=ast.CompareOperationOp.GtEq,
                                    right=ast.ArithmeticOperation(
                                        left=ast.ArrayAccess(
                                            array=ast.Field(chain=["conversion_timestamps"]),
                                            property=ast.Field(chain=["i"])
                                        ),
                                        op=ast.ArithmeticOperationOp.Sub,
                                        right=ast.Constant(value=attribution_window_seconds)
                                    )
                                )
                            ])),
                            ast.Field(chain=["utm_timestamps"])
                        ])
                    ]),
                    ast.Constant(value=1)
                ])
            ),
            
            # Get campaign/source for that timestamp
            ast.Alias(
                alias="fallback_campaign",
                expr=ast.Call(name="if", args=[
                    ast.CompareOperation(
                        left=ast.Field(chain=["last_utm_timestamp"]),
                        op=ast.CompareOperationOp.NotEq,
                        right=ast.Constant(value=None)
                    ),
                    ast.ArrayAccess(
                        array=ast.Field(chain=["utm_campaigns"]),
                        property=ast.Call(name="indexOf", args=[
                            ast.Field(chain=["utm_timestamps"]),
                            ast.Field(chain=["last_utm_timestamp"])
                        ])
                    ),
                    ast.Constant(value="")
                ])
            ),
            
            ast.Alias(
                alias="fallback_source",
                expr=ast.Call(name="if", args=[
                    ast.CompareOperation(
                        left=ast.Field(chain=["last_utm_timestamp"]),
                        op=ast.CompareOperationOp.NotEq,
                        right=ast.Constant(value=None)
                    ),
                    ast.ArrayAccess(
                        array=ast.Field(chain=["utm_sources"]),
                        property=ast.Call(name="indexOf", args=[
                            ast.Field(chain=["utm_timestamps"]),
                            ast.Field(chain=["last_utm_timestamp"])
                        ])
                    ),
                    ast.Constant(value="")
                ])
            )
        ]
        
        # Build FROM with subquery
        from_expr = ast.JoinExpr(table=inner_query)
        
        # Build the query with ARRAY JOIN
        query = ast.SelectQuery(
            select=select_columns,
            select_from=from_expr,
            array_join_op="ARRAY JOIN",
            array_join_list=[
                ast.Alias(
                    expr=ast.Call(name="arrayEnumerate", args=[ast.Field(chain=["conversion_timestamps"])]),
                    alias="i"
                )
            ]
        )
        
        return query
    
    def build_attribution_logic_subquery(self, array_join_query: ast.SelectQuery) -> ast.SelectQuery:
        """Build the subquery that applies attribution logic (campaign and source independently)"""
        
        select_columns: list[ast.Expr] = [
            ast.Field(chain=["person_id"]),
            
            # Campaign attribution (independent)
            ast.Alias(
                alias="campaign_name",
                expr=ast.Call(name="if", args=[
                    ast.Call(name="notEmpty", args=[ast.Field(chain=["conversion_campaign"])]),
                    ast.Field(chain=["conversion_campaign"]),  # Direct attribution
                    ast.Call(name="if", args=[
                        ast.Call(name="notEmpty", args=[ast.Field(chain=["fallback_campaign"])]),
                        ast.Field(chain=["fallback_campaign"]),  # Fallback attribution
                        ast.Constant(value="")
                    ])
                ])
            ),
            
            # Source attribution (independent)
            ast.Alias(
                alias="source_name",
                expr=ast.Call(name="if", args=[
                    ast.Call(name="notEmpty", args=[ast.Field(chain=["conversion_source"])]),
                    ast.Field(chain=["conversion_source"]),  # Direct attribution
                    ast.Call(name="if", args=[
                        ast.Call(name="notEmpty", args=[ast.Field(chain=["fallback_source"])]),
                        ast.Field(chain=["fallback_source"]),  # Fallback attribution
                        ast.Constant(value="")
                    ])
                ])
            ),
            
            # Conversion value
            ast.Alias(alias="conversion_value", expr=self.get_final_conversion_value_expr())
        ]
        
        from_expr = ast.JoinExpr(table=array_join_query)
        
        return ast.SelectQuery(select=select_columns, select_from=from_expr)
    
    def build_final_aggregation_query(self, attribution_query: ast.SelectQuery) -> ast.SelectQuery:
        """Build the final aggregation query"""
        
        # Build coalesce expressions for organic defaults
        campaign_coalesce = ast.Call(name="if", args=[
            ast.Call(name="notEmpty", args=[ast.Field(chain=["campaign_name"])]),
            ast.Field(chain=["campaign_name"]),
            ast.Constant(value=ORGANIC_CAMPAIGN)
        ])
        
        source_coalesce = ast.Call(name="if", args=[
            ast.Call(name="notEmpty", args=[ast.Field(chain=["source_name"])]),
            ast.Field(chain=["source_name"]),
            ast.Constant(value=ORGANIC_SOURCE)
        ])
        
        # Get aggregation expression
        aggregation_expr = self.get_array_based_aggregation_ast()
        
        select_columns = [
            ast.Alias(alias=MarketingSourceAdapter.campaign_name_field, expr=campaign_coalesce),
            ast.Alias(alias=MarketingSourceAdapter.source_name_field, expr=source_coalesce),
            ast.Alias(alias=CONVERSION_GOAL_PREFIX + str(self.index), expr=aggregation_expr),
        ]
        
        from_expr = ast.JoinExpr(table=attribution_query, alias="attributed_conversions")
        
        group_by_exprs = [
            ast.Field(chain=[MarketingSourceAdapter.campaign_name_field]),
            ast.Field(chain=[MarketingSourceAdapter.source_name_field]),
        ]
        
        return ast.SelectQuery(select=select_columns, select_from=from_expr, group_by=group_by_exprs)
    
    def get_final_conversion_value_expr(self) -> ast.Expr:
        """Get the final conversion value expression for the attribution logic"""
        math_type = self.goal.math
        if math_type in [BaseMathType.DAU, "dau"]:
            return ast.Field(chain=["person_id"])
        elif math_type == "sum" or str(math_type).endswith("_sum"):
            return ast.Call(name="toFloat", args=[ast.Field(chain=["conversion_math_value"])])
        else:
            return ast.Constant(value=1)

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

    def get_conversion_value_ast_expr(self) -> ast.Expr:
        """Get conversion value expression as AST based on math type for array collection"""
        math_type = self.goal.math
        math_property = getattr(self.goal, 'math_property', None)
        
        if math_type in [BaseMathType.DAU, "dau"]:
            return ast.Field(chain=["events", "person_id"])
        elif (math_type == "sum" or str(math_type).endswith("_sum")) and math_property:
            # Build: toFloat(ifNull(events.properties.math_property, '0'))
            property_field = ast.Field(chain=["events", "properties", math_property])
            ifnull_expr = ast.Call(name="ifNull", args=[property_field, ast.Constant(value="0")])
            return ast.Call(name="toFloat", args=[ifnull_expr])
        else:
            return ast.Constant(value=1)
    
    def get_array_based_aggregation_ast(self) -> ast.Expr:
        """Get the aggregation expression as AST based on math type"""
        math_type = self.goal.math
        if math_type in [BaseMathType.DAU, "dau"]:
            return ast.Call(name="uniq", args=[ast.Field(chain=["person_id"])])
        elif math_type == "sum" or str(math_type).endswith("_sum"):
            return ast.Call(name="sum", args=[ast.Field(chain=["conversion_value"])])
        else:
            return ast.Call(name="count", args=[])




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
