from dataclasses import dataclass
from typing import Union
import structlog

from posthog.hogql import ast
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

    def generate_person_utm_subquery(self, additional_conditions: list[ast.Expr] | None = None) -> ast.SelectQuery:
        """
        STEP 1: Generate person-level UTM fallback data subquery

        PURPOSE: For each person, find their most recent UTM campaign/source data within the query date range
        This is used as FALLBACK when conversion events don't have their own UTM data
        Date filtering prevents future UTM data from attributing past conversions

        EXAMPLE SQL OUTPUT:
        SELECT
            events.person_id AS person_id,
            argMax(if(utm_campaign IS NOT NULL AND utm_source IS NOT NULL
                     AND utm_campaign != '' AND utm_source != '',
                     utm_campaign, NULL), events.timestamp) AS utm_campaign,
            argMax(if(utm_campaign IS NOT NULL AND utm_source IS NOT NULL
                     AND utm_campaign != '' AND utm_source != '',
                     utm_source, NULL), events.timestamp) AS utm_source
        FROM events
        WHERE events.team_id = 123
          AND events.timestamp >= toDate('2023-01-01')
          AND events.timestamp <= toDate('2023-01-31')
        GROUP BY events.person_id

        EXAMPLE RESULT ROWS:
        person_id | utm_campaign  | utm_source  | (meaning)
        ----------|---------------|-------------|------------------------------------------
        1001      | google_ads    | google      | Person 1001's most recent UTM data (within date range)
        1002      | facebook_ads  | facebook    | Person 1002's most recent UTM data (within date range)
        1003      | NULL          | NULL        | Person 1003 had no complete UTM data in date range

        KEY LOGIC:
        - Only considers events where BOTH campaign AND source exist (complete UTM pair)
        - Uses argMax() to get the most recent complete UTM pair per person WITHIN DATE RANGE
        - Prevents future UTM data from attributing past conversions (temporal consistency)
        - If person had no complete UTM data in date range, returns NULL (not 'organic')
        """
        utm_campaign_field = self.goal.schema_map.get("utm_campaign_name", "utm_campaign")
        utm_source_field = self.goal.schema_map.get("utm_source_name", "utm_source")

        # CONDITION: Both UTM campaign and source must exist and be non-empty
        # This ensures we only use "complete" UTM attribution data
        # Incomplete UTM data (only campaign OR only source) is ignored
        both_utm_exist = ast.And(
            exprs=[
                ast.Call(name="isNotNull", args=[ast.Field(chain=["events", "properties", utm_campaign_field])]),
                ast.Call(name="isNotNull", args=[ast.Field(chain=["events", "properties", utm_source_field])]),
                ast.CompareOperation(
                    left=ast.Field(chain=["events", "properties", utm_campaign_field]),
                    op=ast.CompareOperationOp.NotEq,
                    right=ast.Constant(value=""),
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=["events", "properties", utm_source_field]),
                    op=ast.CompareOperationOp.NotEq,
                    right=ast.Constant(value=""),
                ),
            ]
        )

        # CONDITIONAL EXTRACTION: Extract UTM campaign only if complete UTM pair exists
        # if(both_utm_exist, utm_campaign, NULL)
        # This means: "give me the campaign value, but only if we also have a source"
        campaign_case = ast.Call(
            name="if",
            args=[
                both_utm_exist,
                ast.Field(chain=["events", "properties", utm_campaign_field]),
                ast.Constant(value=None),
            ],
        )

        # CONDITIONAL EXTRACTION: Extract UTM source only if complete UTM pair exists
        # if(both_utm_exist, utm_source, NULL)
        # This means: "give me the source value, but only if we also have a campaign"
        source_case = ast.Call(
            name="if",
            args=[
                both_utm_exist,
                ast.Field(chain=["events", "properties", utm_source_field]),
                ast.Constant(value=None),
            ],
        )

        # MOST RECENT UTM: Use argMax to get the most recent complete UTM data per person
        # argMax(value, timestamp) = "give me the value from the row with the highest timestamp"
        # This gives us the person's GLOBALLY most recent UTM data (no time window filtering)
        utm_campaign_expr = ast.Call(name="argMax", args=[campaign_case, ast.Field(chain=["events", "timestamp"])])
        utm_source_expr = ast.Call(name="argMax", args=[source_case, ast.Field(chain=["events", "timestamp"])])

        # SELECT COLUMNS: What this subquery returns
        select_columns = [
            ast.Alias(alias="person_id", expr=ast.Field(chain=["events", "person_id"])),  # Person identifier
            ast.Alias(alias="utm_campaign", expr=utm_campaign_expr),  # Most recent campaign
            ast.Alias(alias="utm_source", expr=utm_source_expr),  # Most recent source
        ]

        # FROM CLAUSE: Just events table - HogQL will handle person_distinct_ids join automatically
        from_expr = ast.JoinExpr(table=ast.Field(chain=["events"]))

        # WHERE CONDITIONS: Filter by team and apply date range to prevent future attribution
        # We consider UTM data from different event types based on configuration
        where_conditions: list[ast.CompareOperation] = []

        # OPTIONAL OPTIMIZATION: Only look for UTM data in $pageview events to reduce memory usage
        if self.utm_pageview_only:
            where_conditions.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["events", "event"]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value="$pageview"),
                )
            )

        # Add date range conditions to prevent future UTM data from attributing past conversions
        if additional_conditions:
            where_conditions.extend(additional_conditions)

        where_expr = None
        if len(where_conditions) == 1:
            where_expr = where_conditions[0]
        else:
            where_expr = ast.And(exprs=where_conditions)

        # GROUP BY: One row per person
        # This is what triggers the argMax() aggregation - we get the most recent UTM per person
        group_by_exprs = [ast.Field(chain=["events", "person_id"])]

        return ast.SelectQuery(select=select_columns, select_from=from_expr, where=where_expr, group_by=group_by_exprs)

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
        OPTIMIZED: Generate main CTE query with ARRAY-BASED HYBRID ATTRIBUTION (no expensive JOINs)

        PURPOSE: Use single-pass array aggregation instead of expensive JOINs for much better performance
        Supports different date ranges for conversions vs UTM attribution data
        """
        utm_campaign_field = self.goal.schema_map.get("utm_campaign_name", "utm_campaign")
        utm_source_field = self.goal.schema_map.get("utm_source_name", "utm_source")

        # Get conversion math expression (always as string for consistent tuple structure)
        if self.goal.math in [BaseMathType.DAU, "dau"]:
            conversion_value = ast.Call(name="toString", args=[ast.Constant(value=1)])  # For DAU, we count unique persons
        elif self.goal.math in [PropertyMathType.SUM, "sum"] and self.goal.math_property:
            conversion_value = ast.Call(name="toString", args=[
                ast.Call(name="ifNull", args=[
                    ast.Field(chain=["events", "properties", self.goal.math_property]),
                    ast.Constant(value="0")  # Use string "0" instead of numeric 0
                ])
            ])
        else:
            conversion_value = ast.Call(name="toString", args=[ast.Constant(value=1)])  # Default for TOTAL and other math types

        # Build base conversion conditions (event type, action, properties)
        base_conversion_conditions = self.get_base_where_conditions()
        base_conversion_conditions = add_conversion_goal_property_filters(base_conversion_conditions, self.goal, self.team)

        # Convert conditions to AND expression for use in groupArrayIf
        conversion_condition_expr = None
        if base_conversion_conditions:
            if len(base_conversion_conditions) == 1:
                conversion_condition_expr = base_conversion_conditions[0]
            else:
                conversion_condition_expr = ast.And(exprs=base_conversion_conditions)

        # Build UTM pageview conditions
        utm_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview")
            ),
            ast.Call(name="isNotNull", args=[ast.Field(chain=["events", "properties", utm_campaign_field])]),
            ast.Call(name="isNotNull", args=[ast.Field(chain=["events", "properties", utm_source_field])]),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "properties", utm_campaign_field]),
                op=ast.CompareOperationOp.NotEq,
                right=ast.Constant(value=""),
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "properties", utm_source_field]),
                op=ast.CompareOperationOp.NotEq,
                right=ast.Constant(value=""),
            ),
        ]

        # Create AND expression for UTM conditions  
        utm_condition_expr = ast.And(exprs=utm_conditions)

        # Extract date condition from additional_conditions for conversion filtering
        date_condition = None
        non_date_conditions = []
        for cond in additional_conditions:
            if (hasattr(cond, 'left') and hasattr(cond.left, 'chain') 
                and cond.left.chain == ["events", "timestamp"]):
                date_condition = cond
            else:
                non_date_conditions.append(cond)

        # STEP 1: Build inner query that collects all data per person
        inner_select = [
            ast.Alias(alias="person_id", expr=ast.Field(chain=["events", "person_id"])),
            # Collect conversion events WITH date filter
            ast.Alias(
                alias="conversion_events",
                expr=ast.Call(
                    name="groupArrayIf",
                    args=[
                        ast.Call(
                            name="tuple",
                            args=[
                                ast.Field(chain=["events", "timestamp"]),
                                ast.Call(name="ifNull", args=[
                                    ast.Call(name="toString", args=[ast.Field(chain=["events", "properties", utm_campaign_field])]),
                                    ast.Constant(value="")
                                ]),
                                ast.Call(name="ifNull", args=[
                                    ast.Call(name="toString", args=[ast.Field(chain=["events", "properties", utm_source_field])]),
                                    ast.Constant(value="")
                                ]),
                                conversion_value
                            ]
                        ),
                        # FIXED: Properly combine conversion conditions with date filter
                        ast.And(exprs=[
                            expr for expr in [
                                conversion_condition_expr,
                                date_condition
                            ] if expr is not None
                        ]) if conversion_condition_expr or date_condition else ast.Constant(value=True)
                    ]
                )
            ),
            # Collect UTM events (sorted) WITHOUT date filter for broader attribution window
            ast.Alias(
                alias="utm_events",
                expr=ast.Call(
                    name="arraySort",
                    args=[
                        # FIXED: Make sorting deterministic by using timestamp + campaign as sort key
                        ast.Lambda(args=["x"], expr=ast.Call(
                            name="tuple", 
                            args=[
                                ast.Call(name="tupleElement", args=[ast.Field(chain=["x"]), ast.Constant(value=1)]),  # timestamp first
                                ast.Call(name="tupleElement", args=[ast.Field(chain=["x"]), ast.Constant(value=2)])   # campaign second (tie-breaker)
                            ]
                        )),
                        ast.Call(
                            name="groupArrayIf",
                            args=[
                                ast.Call(
                                    name="tuple",
                                    args=[
                                        ast.Field(chain=["events", "timestamp"]),
                                        ast.Call(name="ifNull", args=[
                                            ast.Call(name="toString", args=[ast.Field(chain=["events", "properties", utm_campaign_field])]),
                                            ast.Constant(value="")
                                        ]),
                                        ast.Call(name="ifNull", args=[
                                            ast.Call(name="toString", args=[ast.Field(chain=["events", "properties", utm_source_field])]),
                                            ast.Constant(value="")
                                        ])
                                    ]
                                ),
                                # Only UTM conditions, no date filter for broader attribution window
                                utm_condition_expr
                            ]
                        )
                    ]
                )
            )
        ]

        # Build WHERE clause for events table - use non-date conditions
        where_expr = None
        if non_date_conditions:
            if len(non_date_conditions) == 1:
                where_expr = non_date_conditions[0]
            else:
                where_expr = ast.And(exprs=non_date_conditions)

        # Inner query
        inner_query = ast.SelectQuery(
            select=inner_select,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=where_expr,
            group_by=[ast.Field(chain=["events", "person_id"])],
            having=ast.CompareOperation(
                left=ast.Call(name="length", args=[ast.Field(chain=["conversion_events"])]),
                op=ast.CompareOperationOp.Gt,
                right=ast.Constant(value=0)
            )
        )

        # STEP 2: Build outer query with arrayMap for attribution
        attribution_select = [
            ast.Alias(alias="person_id", expr=ast.Field(chain=["person_id"])),
            ast.Alias(
                alias="attribution_results",
                expr=ast.Call(
                    name="arrayMap",
                    args=[
                        ast.Lambda(
                            args=["conversion_tuple"],
                            expr=ast.Call(
                                name="tuple",
                                args=[
                                    # Campaign attribution: event -> temporal -> organic
                                    ast.Call(
                                        name="if",
                                        args=[
                                            ast.Call(name="notEmpty", args=[ast.Call(name="tupleElement", args=[ast.Field(chain=["conversion_tuple"]), ast.Constant(value=2)])]),
                                            ast.Call(name="tupleElement", args=[ast.Field(chain=["conversion_tuple"]), ast.Constant(value=2)]),  # Use event UTM
                                            ast.Call(
                                                name="if",
                                                args=[
                                                    ast.And(exprs=[
                                                        ast.CompareOperation(
                                                            left=ast.Call(name="length", args=[ast.Field(chain=["utm_events"])]),
                                                            op=ast.CompareOperationOp.Gt,
                                                            right=ast.Constant(value=0)
                                                        ),
                                                        ast.CompareOperation(
                                                            left=ast.Call(
                                                                name="arrayLastIndex",
                                                                args=[
                                                                    ast.Lambda(
                                                                        args=["utm_tuple"],
                                                                        expr=ast.CompareOperation(
                                                                            left=ast.Call(name="tupleElement", args=[ast.Field(chain=["utm_tuple"]), ast.Constant(value=1)]),
                                                                            op=ast.CompareOperationOp.LtEq,
                                                                            right=ast.Call(name="tupleElement", args=[ast.Field(chain=["conversion_tuple"]), ast.Constant(value=1)])
                                                                        )
                                                                    ),
                                                                    ast.Field(chain=["utm_events"])
                                                                ]
                                                            ),
                                                            op=ast.CompareOperationOp.Gt,
                                                            right=ast.Constant(value=0)
                                                        )
                                                    ]),
                                                    # Find last UTM before conversion
                                                    ast.Call(
                                                        name="tupleElement",
                                                        args=[
                                                            ast.Call(
                                                                name="arrayElement",
                                                                args=[
                                                                    ast.Field(chain=["utm_events"]),
                                                                    ast.Call(
                                                                        name="arrayLastIndex",
                                                                        args=[
                                                                            ast.Lambda(
                                                                                args=["utm_tuple"],
                                                                                expr=ast.CompareOperation(
                                                                                    left=ast.Call(name="tupleElement", args=[ast.Field(chain=["utm_tuple"]), ast.Constant(value=1)]),
                                                                                    op=ast.CompareOperationOp.LtEq,
                                                                                    right=ast.Call(name="tupleElement", args=[ast.Field(chain=["conversion_tuple"]), ast.Constant(value=1)])
                                                                                )
                                                                            ),
                                                                            ast.Field(chain=["utm_events"])
                                                                        ]
                                                                    )
                                                                ]
                                                            ),
                                                            ast.Constant(value=2)
                                                        ]
                                                    ),
                                                    ast.Constant(value=ORGANIC_CAMPAIGN)
                                                ]
                                            )
                                        ]
                                    ),
                                    # Source attribution (same logic)
                                    ast.Call(
                                        name="if",
                                        args=[
                                            ast.Call(name="notEmpty", args=[ast.Call(name="tupleElement", args=[ast.Field(chain=["conversion_tuple"]), ast.Constant(value=3)])]),
                                            ast.Call(name="tupleElement", args=[ast.Field(chain=["conversion_tuple"]), ast.Constant(value=3)]),  # Use event UTM
                                            ast.Call(
                                                name="if",
                                                args=[
                                                    ast.And(exprs=[
                                                        ast.CompareOperation(
                                                            left=ast.Call(name="length", args=[ast.Field(chain=["utm_events"])]),
                                                            op=ast.CompareOperationOp.Gt,
                                                            right=ast.Constant(value=0)
                                                        ),
                                                        ast.CompareOperation(
                                                            left=ast.Call(
                                                                name="arrayLastIndex",
                                                                args=[
                                                                    ast.Lambda(
                                                                        args=["utm_tuple"],
                                                                        expr=ast.CompareOperation(
                                                                            left=ast.Call(name="tupleElement", args=[ast.Field(chain=["utm_tuple"]), ast.Constant(value=1)]),
                                                                            op=ast.CompareOperationOp.LtEq,
                                                                            right=ast.Call(name="tupleElement", args=[ast.Field(chain=["conversion_tuple"]), ast.Constant(value=1)])
                                                                        )
                                                                    ),
                                                                    ast.Field(chain=["utm_events"])
                                                                ]
                                                            ),
                                                            op=ast.CompareOperationOp.Gt,
                                                            right=ast.Constant(value=0)
                                                        )
                                                    ]),
                                                    # Find last UTM before conversion
                                                    ast.Call(
                                                        name="tupleElement",
                                                        args=[
                                                            ast.Call(
                                                                name="arrayElement",
                                                                args=[
                                                                    ast.Field(chain=["utm_events"]),
                                                                    ast.Call(
                                                                        name="arrayLastIndex",
                                                                        args=[
                                                                            ast.Lambda(
                                                                                args=["utm_tuple"],
                                                                                expr=ast.CompareOperation(
                                                                                    left=ast.Call(name="tupleElement", args=[ast.Field(chain=["utm_tuple"]), ast.Constant(value=1)]),
                                                                                    op=ast.CompareOperationOp.LtEq,
                                                                                    right=ast.Call(name="tupleElement", args=[ast.Field(chain=["conversion_tuple"]), ast.Constant(value=1)])
                                                                                )
                                                                            ),
                                                                            ast.Field(chain=["utm_events"])
                                                                        ]
                                                                    )
                                                                ]
                                                            ),
                                                            ast.Constant(value=3)
                                                        ]
                                                    ),
                                                    ast.Constant(value=ORGANIC_SOURCE)
                                                ]
                                            )
                                        ]
                                    ),
                                    # Conversion value
                                    ast.Call(name="tupleElement", args=[ast.Field(chain=["conversion_tuple"]), ast.Constant(value=4)])
                                ]
                            )
                        ),
                        ast.Field(chain=["conversion_events"])
                    ]
                )
            )
        ]

        attribution_query = ast.SelectQuery(
            select=attribution_select,
            select_from=ast.JoinExpr(table=inner_query, alias="person_data")
        )

        # STEP 3: Final query with array join and aggregation
        final_select = [
            ast.Alias(
                alias=MarketingSourceAdapter.campaign_name_field,
                expr=ast.Call(name="tupleElement", args=[ast.Field(chain=["result_tuple"]), ast.Constant(value=1)])
            ),
            ast.Alias(
                alias=MarketingSourceAdapter.source_name_field,
                expr=ast.Call(name="tupleElement", args=[ast.Field(chain=["result_tuple"]), ast.Constant(value=2)])
            ),
            ast.Alias(
                alias=CONVERSION_GOAL_PREFIX + str(self.index),
                expr=ast.Call(
                    name="uniq" if self.goal.math in [BaseMathType.DAU, "dau"] else "sum",
                    args=[
                        ast.Field(chain=["person_id"]) if self.goal.math in [BaseMathType.DAU, "dau"] 
                        else ast.Call(name="toFloat", args=[ast.Call(name="tupleElement", args=[ast.Field(chain=["result_tuple"]), ast.Constant(value=3)])])
                    ]
                )
            ),
        ]

        return ast.SelectQuery(
            select=final_select,
            select_from=ast.JoinExpr(table=attribution_query, alias="attribution_data"),
            array_join_op="ARRAY JOIN",
            array_join_list=[ast.Alias(alias="result_tuple", expr=ast.Field(chain=["attribution_results"]))],
            group_by=[
                ast.Call(name="tupleElement", args=[ast.Field(chain=["result_tuple"]), ast.Constant(value=1)]),  # campaign
                ast.Call(name="tupleElement", args=[ast.Field(chain=["result_tuple"]), ast.Constant(value=2)])   # source
            ]
        )

    def generate_conversion_data_with_utm_subquery(self, additional_conditions: list[ast.Expr]) -> ast.SelectQuery:
        """
        STEP 2: Generate conversion data subquery WITH event-level UTM data

        PURPOSE: Get all conversion events with their direct UTM parameters (if any)
        This extracts UTM data directly from each conversion event's properties

        EXAMPLE SQL OUTPUT:
        SELECT
            events.person_id AS person_id,
            count(*) AS conversion_value,                    -- OR sum(revenue) for sum math
            events.properties.utm_campaign AS event_utm_campaign,
            events.properties.utm_source AS event_utm_source
        FROM events
        WHERE
            events.team_id = 123
            AND events.event = 'purchase'
            AND events.timestamp >= '2023-01-01'
            AND events.timestamp <= '2023-01-31'
        GROUP BY
            events.person_id,
            events.properties.utm_campaign,
            events.properties.utm_source

        EXAMPLE RESULT ROWS:
        person_id | conversion_value | event_utm_campaign | event_utm_source | (meaning)
        ----------|------------------|--------------------|-----------------|---------------------------------
        1001      | 2                | google_ads         | google          | Person 1001: 2 purchases w/ UTM
        1002      | 1                | NULL               | NULL            | Person 1002: 1 purchase w/o UTM
        1003      | 150.50           | facebook_ads       | facebook        | Person 1003: $150.50 w/ UTM

        KEY BEHAVIOR:
        - Each row represents conversion events from one person with the same UTM combination
        - event_utm_campaign/event_utm_source are NULL if the conversion event had no UTM data
        - This NULL data triggers the person-level fallback logic in the main query
        """
        utm_campaign_field = self.goal.schema_map.get("utm_campaign_name", "utm_campaign")
        utm_source_field = self.goal.schema_map.get("utm_source_name", "utm_source")

        # CONVERSION VALUE: Calculate based on math type (count, dau, sum)
        if self.goal.math in [BaseMathType.DAU, "dau"]:
            # For DAU, we want to count each person only once per UTM combination
            # Each row represents a person-UTM combination, so 1 per row
            conversion_expr = ast.Constant(value=1)
        else:
            # For count/sum, use the regular aggregation logic
            # This will be count(*) for count math or sum(property) for sum math
            conversion_expr = self.get_select_field()

        # EVENT UTM EXTRACTION: Get UTM data directly from the conversion event
        # These may be NULL if the conversion event doesn't have UTM parameters
        # NULL values will trigger person-level fallback in the main query
        event_utm_campaign = ast.Field(chain=["events", "properties", utm_campaign_field])
        event_utm_source = ast.Field(chain=["events", "properties", utm_source_field])

        # SELECT COLUMNS: What this subquery returns
        select_columns = [
            ast.Alias(alias="person_id", expr=ast.Field(chain=["events", "person_id"])),  # Person who converted
            ast.Alias(
                alias="conversion_timestamp", expr=ast.Field(chain=["events", "timestamp"])
            ),  # Conversion timestamp for JOIN
            ast.Alias(alias="conversion_value", expr=conversion_expr),  # Conversion value/count
            ast.Alias(alias="event_utm_campaign", expr=event_utm_campaign),  # Event's UTM campaign (may be NULL)
            ast.Alias(alias="event_utm_source", expr=event_utm_source),  # Event's UTM source (may be NULL)
        ]

        # FROM CLAUSE: Just events table - HogQL will handle person_distinct_ids join automatically
        from_expr = ast.JoinExpr(table=ast.Field(chain=["events"]))

        # WHERE CONDITIONS: Filter for conversion events
        # This combines base conditions (team, event/action) with property filters and date range
        where_conditions = self.get_base_where_conditions()
        where_conditions = add_conversion_goal_property_filters(where_conditions, self.goal, self.team)
        where_conditions.extend(additional_conditions)

        where_expr = None
        if where_conditions:
            if len(where_conditions) == 1:
                where_expr = where_conditions[0]
            else:
                where_expr = ast.And(exprs=where_conditions)

        # GROUP BY: Aggregate by person, timestamp, and UTM combination
        # This is CRITICAL for ClickHouse: we SELECT these fields, so we must GROUP BY them
        # Each row represents one conversion event with its specific timestamp and UTM data
        group_by_exprs = [
            ast.Field(chain=["events", "person_id"]),
            ast.Field(chain=["events", "timestamp"]),
            event_utm_campaign,
            event_utm_source,
        ]

        return ast.SelectQuery(select=select_columns, select_from=from_expr, where=where_expr, group_by=group_by_exprs)

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

    def generate_person_utm_with_temporal_attribution_subquery(
        self, additional_conditions: list[ast.Expr] | None = None
    ) -> ast.SelectQuery:
        """
        TEMPORAL ATTRIBUTION: Always find nearest UTM pageview before conversion

        PURPOSE: For each conversion event, find the most recent UTM data from BEFORE that specific conversion
        Ignores query_date_range for UTM lookback - searches ALL historical UTM events
        This ensures conversions are always attributed to their nearest valid UTM touchpoint
        """
        utm_campaign_field = self.goal.schema_map.get("utm_campaign_name", "utm_campaign")
        utm_source_field = self.goal.schema_map.get("utm_source_name", "utm_source")

        # Get conversion events (apply date filtering only to conversions)
        conversion_conditions = self.get_base_where_conditions()
        if additional_conditions:
            conversion_conditions.extend(additional_conditions)

        # Create conversions CTE
        conversions_cte = ast.SelectQuery(
            select=[
                ast.Alias(alias="person_id", expr=ast.Field(chain=["events", "person_id"])),
                ast.Alias(alias="conversion_timestamp", expr=ast.Field(chain=["events", "timestamp"])),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=conversion_conditions) if len(conversion_conditions) > 1 else conversion_conditions[0],
        )

        # Create UTM events CTE (no date filtering - we need historical data)
        utm_conditions = [
            # Complete UTM data only
            ast.Call(name="isNotNull", args=[ast.Field(chain=["events", "properties", utm_campaign_field])]),
            ast.Call(name="isNotNull", args=[ast.Field(chain=["events", "properties", utm_source_field])]),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "properties", utm_campaign_field]),
                op=ast.CompareOperationOp.NotEq,
                right=ast.Constant(value=""),
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "properties", utm_source_field]),
                op=ast.CompareOperationOp.NotEq,
                right=ast.Constant(value=""),
            ),
        ]

        # PAGEVIEW OPTIMIZATION: Only look for UTM data in $pageview events to reduce searching scope
        if self.utm_pageview_only:
            utm_conditions.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["events", "event"]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value="$pageview"),
                )
            )

        utm_events_cte = ast.SelectQuery(
            select=[
                ast.Alias(alias="person_id", expr=ast.Field(chain=["events", "person_id"])),
                ast.Alias(alias="timestamp", expr=ast.Field(chain=["events", "timestamp"])),
                ast.Alias(alias="utm_campaign", expr=ast.Field(chain=["events", "properties", utm_campaign_field])),
                ast.Alias(alias="utm_source", expr=ast.Field(chain=["events", "properties", utm_source_field])),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=utm_conditions) if len(utm_conditions) > 1 else utm_conditions[0],
        )

        # Main query: Join conversions with UTM events and find temporal attribution
        conversions_from = ast.JoinExpr(table=conversions_cte, alias="conversions")

        # Cross join with UTM events to get all combinations, then filter and aggregate
        utm_join = ast.JoinExpr(
            join_type="LEFT JOIN",
            table=utm_events_cte,
            alias="utm_events",
            constraint=ast.JoinConstraint(
                expr=ast.And(
                    exprs=[
                        # Same person
                        ast.CompareOperation(
                            left=ast.Field(chain=["conversions", "person_id"]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Field(chain=["utm_events", "person_id"]),
                        ),
                        # UTM event before or at conversion (includes simultaneous events)
                        ast.CompareOperation(
                            left=ast.Field(chain=["utm_events", "timestamp"]),
                            op=ast.CompareOperationOp.LtEq,
                            right=ast.Field(chain=["conversions", "conversion_timestamp"]),
                        ),
                    ]
                ),
                constraint_type="ON",
            ),
        )

        conversions_from.next_join = utm_join

        # Use argMax to get the most recent UTM data before each conversion
        utm_campaign_expr = ast.Call(
            name="argMax",
            args=[ast.Field(chain=["utm_events", "utm_campaign"]), ast.Field(chain=["utm_events", "timestamp"])],
        )

        utm_source_expr = ast.Call(
            name="argMax",
            args=[ast.Field(chain=["utm_events", "utm_source"]), ast.Field(chain=["utm_events", "timestamp"])],
        )

        # Group by person AND conversion timestamp for per-conversion attribution
        # This gives each individual conversion its own temporal attribution lookup
        # Instead of person-level attribution, we now get conversion-level attribution
        return ast.SelectQuery(
            select=[
                ast.Alias(alias="person_id", expr=ast.Field(chain=["conversions", "person_id"])),
                ast.Alias(
                    alias="conversion_timestamp", expr=ast.Field(chain=["conversions", "conversion_timestamp"])
                ),  # For JOIN
                ast.Alias(alias="utm_campaign", expr=utm_campaign_expr),
                ast.Alias(alias="utm_source", expr=utm_source_expr),
            ],
            select_from=conversions_from,
            group_by=[
                ast.Field(chain=["conversions", "person_id"]),
                ast.Field(chain=["conversions", "conversion_timestamp"]),
            ],
        )


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
