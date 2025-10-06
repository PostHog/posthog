from dataclasses import dataclass
from typing import Optional, Union

from posthog.schema import (
    BaseMathType,
    ConversionGoalFilter1,
    ConversionGoalFilter2,
    ConversionGoalFilter3,
    PropertyMathType,
)

from posthog.hogql import ast
from posthog.hogql.property import action_to_expr, property_to_expr

from posthog.models import Action, Team

from .marketing_analytics_config import MarketingAnalyticsConfig

DAY_IN_SECONDS = 86400


@dataclass
class ConversionGoalProcessor:
    """
    Processes conversion goals for marketing analytics queries.

    This class handles two main query types:
    1. Array-based attribution: For Events/Actions with sophisticated UTM tracking
    2. Direct field access: For DataWarehouse nodes with simple field mapping
    """

    goal: Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3]
    index: int
    team: Team
    config: MarketingAnalyticsConfig

    def get_cte_name(self) -> str:
        """Get unique CTE name for this conversion goal"""
        return self.goal.conversion_goal_id

    def get_table_name(self) -> str:
        """Get table name for querying based on goal type"""
        if self.goal.kind in ["EventsNode", "ActionsNode"]:
            return "events"
        elif self.goal.kind == "DataWarehouseNode" and isinstance(self.goal, ConversionGoalFilter3):
            return self.goal.table_name
        return "events"

    def get_utm_expressions(self) -> tuple[ast.Expr, ast.Expr]:
        """Build UTM campaign and source expressions for different node types"""
        schema_map = self.goal.schema_map
        campaign_field = schema_map.get("utm_campaign_name", "utm_campaign")
        source_field = schema_map.get("utm_source_name", "utm_source")

        if self.goal.kind in ["EventsNode", "ActionsNode"]:
            # For events table, UTM data is in properties
            return (
                ast.Field(chain=["events", "properties", campaign_field]),
                ast.Field(chain=["events", "properties", source_field]),
            )
        else:
            # For data warehouse, UTM data is in direct columns
            return (
                ast.Field(chain=[campaign_field]),
                ast.Field(chain=[source_field]),
            )

    def get_select_field(self) -> ast.Expr:
        """Build select field expression based on math aggregation type"""
        math_type = self.goal.math

        if math_type in [BaseMathType.DAU, "dau"]:
            return self._build_dau_select()
        elif math_type in ["sum", PropertyMathType.SUM] or str(math_type).endswith("_sum"):
            return self._build_sum_select()
        else:
            return ast.Call(name="count", args=[ast.Constant(value="*")])

    def _build_dau_select(self) -> ast.Expr:
        """Build DAU (Daily Active Users) select expression"""
        if self.goal.kind == "DataWarehouseNode":
            schema_map = self.goal.schema_map
            distinct_id_field = schema_map.get("distinct_id_field", self.config.default_distinct_id_field)
            return ast.Call(name="uniq", args=[ast.Field(chain=[distinct_id_field])])
        return ast.Call(name="uniq", args=[ast.Field(chain=["events", self.config.default_distinct_id_field])])

    def _build_sum_select(self) -> ast.Expr:
        """Build SUM aggregation select expression"""
        math_property = self.goal.math_property
        if not math_property:
            return ast.Constant(value=0)

        if self.goal.kind == "DataWarehouseNode":
            property_field = ast.Field(chain=[math_property])
        else:
            property_field = ast.Field(chain=["events", "properties", math_property])

        return ast.Call(
            name="round",
            args=[
                ast.Call(name="sum", args=[ast.Call(name="toFloat", args=[property_field])]),
                ast.Constant(value=self.config.decimal_precision),
            ],
        )

    def get_base_where_conditions(self) -> list[ast.Expr]:
        """Build base WHERE conditions for conversion goal filtering"""
        conditions: list[ast.Expr] = []

        if self.goal.kind == "EventsNode":
            event_name = self.goal.event
            if event_name:
                conditions.append(
                    ast.CompareOperation(
                        left=ast.Field(chain=["events", "event"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value=event_name),
                    )
                )
        elif self.goal.kind == "ActionsNode":
            action_id = self.goal.id
            if action_id:
                action = Action.objects.get(pk=int(action_id), team__project_id=self.team.project_id)
                conditions.append(action_to_expr(action))

        return conditions

    def get_date_field(self) -> str:
        """Get appropriate timestamp field based on goal type"""
        if self.goal.kind == "DataWarehouseNode":
            schema_map = self.goal.schema_map
            return schema_map.get("timestamp_field", "timestamp")
        return "events.timestamp"

    def generate_cte_query(self, additional_conditions: list[ast.Expr]) -> ast.SelectQuery:
        """
        Generate main CTE query for conversion goal.

        Routes to appropriate query type based on goal configuration.
        """
        if self.goal.kind in ["EventsNode", "ActionsNode"]:
            return self._generate_array_based_query(additional_conditions)
        return self._generate_direct_query(additional_conditions)

    def _generate_array_based_query(self, additional_conditions: list[ast.Expr]) -> ast.SelectQuery:
        """Generate array-based query with attribution logic for Events/Actions"""
        if self.config.max_attribution_window_days > 0:
            return self._generate_funnel_query(additional_conditions)
        return self._generate_direct_query(additional_conditions)

    def _generate_funnel_query(self, additional_conditions: list[ast.Expr]) -> ast.SelectQuery:
        """Generate multi-step funnel query with attribution window"""
        conversion_event: Optional[str] = self.goal.event if self.goal.kind == "EventsNode" else None

        # Build complete WHERE conditions
        where_conditions = self.get_base_where_conditions()
        where_conditions = add_conversion_goal_property_filters(where_conditions, self.goal, self.team)
        where_conditions.extend(additional_conditions)

        # Build nested query structure for attribution
        attribution_window_seconds = self.config.max_attribution_window_days * DAY_IN_SECONDS
        array_collection = self._build_array_collection_subquery(conversion_event, where_conditions)
        array_join = self._build_array_join_subquery(array_collection, attribution_window_seconds)
        attribution = self._build_attribution_logic_subquery(array_join)

        return self._build_final_aggregation_query(attribution)

    def _build_array_collection_subquery(
        self, conversion_event: Optional[str], where_conditions: list[ast.Expr]
    ) -> ast.SelectQuery:
        """Build subquery that collects arrays of conversion and UTM data per person"""
        schema_map = self.goal.schema_map
        utm_campaign_field = schema_map.get("utm_campaign_name", "utm_campaign")
        utm_source_field = schema_map.get("utm_source_name", "utm_source")

        # Build WHERE clause with clean separation of concerns
        final_where = self._build_comprehensive_where_clause(
            conversion_event, where_conditions, utm_campaign_field, utm_source_field
        )

        # Build SELECT columns
        select_columns: list[ast.Expr] = [
            ast.Field(chain=["events", "person_id"]),
            self._build_conversion_timestamps_array(conversion_event),
            self._build_conversion_math_values_array(conversion_event),
            self._build_conversion_utm_array("conversion_campaigns", conversion_event, utm_campaign_field),
            self._build_conversion_utm_array("conversion_sources", conversion_event, utm_source_field),
            self._build_utm_pageview_array("utm_timestamps", utm_campaign_field, utm_source_field, "timestamp"),
            self._build_utm_pageview_array("utm_campaigns", utm_campaign_field, utm_source_field, utm_campaign_field),
            self._build_utm_pageview_array("utm_sources", utm_campaign_field, utm_source_field, utm_source_field),
        ]

        # Build HAVING clause
        having_expr = ast.CompareOperation(
            left=ast.Call(name="length", args=[ast.Field(chain=["conversion_timestamps"])]),
            op=ast.CompareOperationOp.Gt,
            right=ast.Constant(value=0),
        )

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=final_where,
            group_by=[ast.Field(chain=["events", "person_id"])],
            having=having_expr,
        )

    def _build_comprehensive_where_clause(
        self,
        conversion_event: Optional[str],
        input_conditions: list[ast.Expr],
        utm_campaign_field: str,
        utm_source_field: str,
    ) -> ast.Expr:
        """Build complete WHERE clause with proper condition separation"""

        # Separate input conditions by type
        date_conditions = [c for c in input_conditions if self._is_date_condition(c)]
        non_event_conditions = [
            c
            for c in input_conditions
            if not self._is_date_condition(c) and not self._is_event_condition(c, conversion_event)
        ]

        # Build event-specific conditions
        event_filter: ast.Expr
        if conversion_event:
            # For specific conversion events, we need both conversion and pageview logic
            if conversion_event == "$pageview":
                # For pageview conversions, we only need attribution pageviews (with UTM data).
                # No need for separate conversion filter since conversion IS the pageview.
                event_filter = self._build_pageview_event_filter(date_conditions, utm_campaign_field, utm_source_field)
            else:
                # For non-pageview conversions, use both filters (no overlap possible)
                event_filter = ast.Or(
                    exprs=[
                        self._build_conversion_event_filter(conversion_event, date_conditions),
                        self._build_pageview_event_filter(date_conditions, utm_campaign_field, utm_source_field),
                    ]
                )
        elif self.goal.kind == "ActionsNode" and self.config.max_attribution_window_days > 0:
            # For ActionsNode with attribution, we need both action events and pageview events
            action_conditions = self.get_base_where_conditions()
            action_filter = self._build_action_event_filter(action_conditions, date_conditions)
            pageview_filter = self._build_pageview_event_filter(date_conditions, utm_campaign_field, utm_source_field)
            event_filter = ast.Or(exprs=[action_filter, pageview_filter])
        else:
            # For general queries, apply date conditions to all events
            event_filter = self._build_general_event_filter(date_conditions)

        # Combine all conditions
        all_conditions = [event_filter, *non_event_conditions]
        return ast.And(exprs=all_conditions) if len(all_conditions) > 1 else all_conditions[0]

    def _build_action_event_filter(
        self, action_conditions: list[ast.Expr], date_conditions: list[ast.Expr]
    ) -> ast.Expr:
        """Build filter for action events with their specific date constraints"""
        conditions: list[ast.Expr] = []

        # Add action conditions (this includes the action_to_expr logic)
        conditions.extend(action_conditions)

        # Apply regular date conditions to action events
        for date_condition in date_conditions:
            if isinstance(date_condition, ast.CompareOperation):
                conditions.append(
                    ast.CompareOperation(
                        left=ast.Field(chain=["events", "timestamp"]),
                        op=date_condition.op,
                        right=self._ensure_datetime_call(date_condition.right),
                    )
                )

        return ast.And(exprs=conditions) if conditions else ast.Constant(value=True)

    def _build_conversion_event_filter(self, conversion_event: str, date_conditions: list[ast.Expr]) -> ast.Expr:
        """Build filter for conversion events with their specific date constraints"""
        conditions: list[ast.Expr] = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=conversion_event),
            )
        ]

        # Apply regular date conditions to conversion events
        for date_condition in date_conditions:
            if isinstance(date_condition, ast.CompareOperation):
                conditions.append(
                    ast.CompareOperation(
                        left=ast.Field(chain=["events", "timestamp"]),
                        op=date_condition.op,
                        right=self._ensure_datetime_call(date_condition.right),
                    )
                )

        return ast.And(exprs=conditions)

    def _build_pageview_event_filter(
        self, date_conditions: list[ast.Expr], utm_campaign_field: str, utm_source_field: str
    ) -> ast.Expr:
        """Build filter for pageview events with UTM requirements and extended date range"""
        conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview"),
            ),
            self._build_utm_not_empty_condition(utm_campaign_field),
            self._build_utm_not_empty_condition(utm_source_field),
        ]

        # Apply extended date conditions for pageviews (attribution window)
        attribution_window_seconds = self.config.max_attribution_window_days * DAY_IN_SECONDS
        for date_condition in date_conditions:
            if isinstance(date_condition, ast.CompareOperation):
                if date_condition.op == ast.CompareOperationOp.GtEq:
                    # Extend start date backwards by attribution window
                    conditions.append(
                        ast.CompareOperation(
                            left=ast.Field(chain=["events", "timestamp"]),
                            op=ast.CompareOperationOp.GtEq,
                            right=ast.ArithmeticOperation(
                                left=self._ensure_datetime_call(date_condition.right),
                                op=ast.ArithmeticOperationOp.Sub,
                                right=ast.Call(
                                    name="toIntervalSecond", args=[ast.Constant(value=attribution_window_seconds)]
                                ),
                            ),
                        )
                    )
                elif date_condition.op == ast.CompareOperationOp.LtEq:
                    conditions.append(
                        ast.CompareOperation(
                            left=ast.Field(chain=["events", "timestamp"]),
                            op=ast.CompareOperationOp.LtEq,
                            right=self._ensure_datetime_call(date_condition.right),
                        )
                    )

        return ast.And(exprs=conditions)

    def _build_general_event_filter(self, date_conditions: list[ast.Expr]) -> ast.Expr:
        """Build filter for general case when no specific conversion event is defined"""
        if not date_conditions:
            return ast.Constant(value=True)

        # Apply date conditions directly to all events
        conditions: list[ast.Expr] = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=condition.op,
                right=self._ensure_datetime_call(condition.right),
            )
            for condition in date_conditions
            if isinstance(condition, ast.CompareOperation)
        ]

        return ast.And(exprs=conditions) if conditions else ast.Constant(value=True)

    def _build_utm_not_empty_condition(self, utm_field: str) -> ast.Call:
        """Build UTM not empty condition"""
        return ast.Call(
            name="notEmpty",
            args=[
                ast.Call(
                    name="toString",
                    args=[
                        ast.Call(
                            name="ifNull",
                            args=[
                                ast.Field(chain=["events", "properties", utm_field]),
                                ast.Constant(value=""),
                            ],
                        )
                    ],
                )
            ],
        )

    def _build_conversion_timestamps_array(self, conversion_event: Optional[str]) -> ast.Alias:
        """Build conversion timestamps array"""
        return ast.Alias(
            alias="conversion_timestamps",
            expr=ast.Call(
                name="arrayFilter",
                args=[
                    ast.Lambda(
                        args=["x"],
                        expr=ast.CompareOperation(
                            left=ast.Field(chain=["x"]),
                            op=ast.CompareOperationOp.Gt,
                            right=ast.Constant(value=0),
                        ),
                    ),
                    ast.Call(
                        name="groupArray",
                        args=[
                            ast.Call(
                                name="if",
                                args=[
                                    self._build_conversion_event_condition(conversion_event),
                                    ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])]),
                                    ast.Constant(value=0),
                                ],
                            )
                        ],
                    ),
                ],
            ),
        )

    def _build_conversion_math_values_array(self, conversion_event: Optional[str]) -> ast.Alias:
        """Build conversion math values array"""
        return ast.Alias(
            alias="conversion_math_values",
            expr=ast.Call(
                name="arrayFilter",
                args=[
                    ast.Lambda(
                        args=["x"],
                        expr=ast.CompareOperation(
                            left=ast.Field(chain=["x"]),
                            op=ast.CompareOperationOp.Gt,
                            right=ast.Constant(value=0),
                        ),
                    ),
                    ast.Call(
                        name="groupArray",
                        args=[
                            ast.Call(
                                name="if",
                                args=[
                                    self._build_conversion_event_condition(conversion_event),
                                    self._get_conversion_value_expr(),
                                    ast.Constant(value=0),
                                ],
                            )
                        ],
                    ),
                ],
            ),
        )

    def _build_conversion_event_condition(self, conversion_event: Optional[str]) -> ast.Expr:
        """Build condition for conversion event matching"""
        if conversion_event:
            return ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=conversion_event),
            )

        # For ActionsNode (when conversion_event is None), we need to use the action condition
        # instead of matching all events
        if self.goal.kind == "ActionsNode":
            action_id = self.goal.id
            if action_id:
                try:
                    action = Action.objects.get(pk=int(action_id), team__project_id=self.team.project_id)
                    return action_to_expr(action)
                except Action.DoesNotExist:
                    return ast.Constant(value=False)

        # Fallback for other cases
        return ast.Constant(value=True)

    def _get_conversion_value_expr(self) -> ast.Expr:
        """Get conversion value expression for array collection"""
        math_type = self.goal.math

        if math_type in [BaseMathType.DAU, "dau"]:
            return ast.Call(name="toFloat", args=[ast.Constant(value=1)])
        elif math_type in ["sum", PropertyMathType.SUM] or str(math_type).endswith("_sum"):
            math_property = self.goal.math_property
            if math_property:
                property_field = ast.Field(chain=["events", "properties", math_property])
                to_float_expr = ast.Call(name="toFloat", args=[property_field])
                return ast.Call(name="coalesce", args=[to_float_expr, ast.Constant(value=0.0)])

        return ast.Call(name="toFloat", args=[ast.Constant(value=1)])

    def _build_conversion_utm_array(self, alias: str, conversion_event: Optional[str], utm_field: str) -> ast.Alias:
        """Build array for conversion event UTM data"""
        return ast.Alias(
            alias=alias,
            expr=ast.Call(
                name="arrayFilter",
                args=[
                    ast.Lambda(
                        args=["x"],
                        expr=ast.Call(name="notEmpty", args=[ast.Call(name="toString", args=[ast.Field(chain=["x"])])]),
                    ),
                    ast.Call(
                        name="groupArray",
                        args=[
                            ast.Call(
                                name="if",
                                args=[
                                    self._build_conversion_event_condition(conversion_event),
                                    ast.Call(
                                        name="toString",
                                        args=[
                                            ast.Call(
                                                name="ifNull",
                                                args=[
                                                    ast.Field(chain=["events", "properties", utm_field]),
                                                    ast.Constant(value=""),
                                                ],
                                            )
                                        ],
                                    ),
                                    ast.Constant(value=""),
                                ],
                            )
                        ],
                    ),
                ],
            ),
        )

    def _build_utm_pageview_array(
        self, alias: str, utm_campaign_field: str, utm_source_field: str, return_field: str
    ) -> ast.Alias:
        """Build array for UTM pageview data"""
        pageview_with_utm = ast.And(
            exprs=[
                ast.CompareOperation(
                    left=ast.Field(chain=["events", "event"]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value="$pageview"),
                ),
                self._build_utm_not_empty_condition(utm_campaign_field),
                self._build_utm_not_empty_condition(utm_source_field),
            ]
        )
        return_expr: ast.Expr
        false_value: ast.Expr
        filter_expr: ast.Expr
        if return_field == "timestamp":
            return_expr = ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])])
            false_value = ast.Constant(value=0)
            filter_expr = ast.CompareOperation(
                left=ast.Field(chain=["x"]),
                op=ast.CompareOperationOp.Gt,
                right=ast.Constant(value=0),
            )
        else:
            return_expr = ast.Call(
                name="toString",
                args=[
                    ast.Call(
                        name="ifNull",
                        args=[
                            ast.Field(chain=["events", "properties", return_field]),
                            ast.Constant(value=""),
                        ],
                    )
                ],
            )
            false_value = ast.Constant(value="")
            filter_expr = ast.Call(name="notEmpty", args=[ast.Field(chain=["x"])])

        return ast.Alias(
            alias=alias,
            expr=ast.Call(
                name="arrayFilter",
                args=[
                    ast.Lambda(args=["x"], expr=filter_expr),
                    ast.Call(
                        name="groupArray",
                        args=[ast.Call(name="if", args=[pageview_with_utm, return_expr, false_value])],
                    ),
                ],
            ),
        )

    def _build_array_join_subquery(
        self, inner_query: ast.SelectQuery, attribution_window_seconds: int
    ) -> ast.SelectQuery:
        """Build subquery with ARRAY JOIN and attribution window logic"""
        select_columns: list[ast.Expr] = [
            ast.Field(chain=["person_id"]),
            ast.Alias(
                alias="conversion_time",
                expr=ast.ArrayAccess(
                    array=ast.Field(chain=["conversion_timestamps"]),
                    property=ast.Field(chain=["i"]),
                ),
            ),
            ast.Alias(
                alias="conversion_math_value",
                expr=ast.ArrayAccess(
                    array=ast.Field(chain=["conversion_math_values"]),
                    property=ast.Field(chain=["i"]),
                ),
            ),
            ast.Alias(
                alias="conversion_campaign",
                expr=ast.ArrayAccess(
                    array=ast.Field(chain=["conversion_campaigns"]),
                    property=ast.Field(chain=["i"]),
                ),
            ),
            ast.Alias(
                alias="conversion_source",
                expr=ast.ArrayAccess(
                    array=ast.Field(chain=["conversion_sources"]),
                    property=ast.Field(chain=["i"]),
                ),
            ),
            self._build_last_utm_timestamp_expr(attribution_window_seconds),
            self._build_fallback_utm_expr("fallback_campaign", "utm_campaigns"),
            self._build_fallback_utm_expr("fallback_source", "utm_sources"),
        ]

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=inner_query),
            array_join_op="ARRAY JOIN",
            array_join_list=[
                ast.Alias(
                    expr=ast.Call(name="arrayEnumerate", args=[ast.Field(chain=["conversion_timestamps"])]),
                    alias="i",
                )
            ],
        )

    def _build_last_utm_timestamp_expr(self, attribution_window_seconds: int) -> ast.Alias:
        """Build expression to find most recent UTM pageview within attribution window"""
        return ast.Alias(
            alias="last_utm_timestamp",
            expr=ast.Call(
                name=self.config.default_attribution_mode,
                args=[
                    ast.Call(
                        name="arrayFilter",
                        args=[
                            ast.Lambda(
                                args=["x"],
                                expr=ast.And(
                                    exprs=[
                                        ast.CompareOperation(
                                            left=ast.Field(chain=["x"]),
                                            op=ast.CompareOperationOp.LtEq,
                                            right=ast.ArrayAccess(
                                                array=ast.Field(chain=["conversion_timestamps"]),
                                                property=ast.Field(chain=["i"]),
                                            ),
                                        ),
                                        ast.CompareOperation(
                                            left=ast.Field(chain=["x"]),
                                            op=ast.CompareOperationOp.GtEq,
                                            right=ast.ArithmeticOperation(
                                                left=ast.ArrayAccess(
                                                    array=ast.Field(chain=["conversion_timestamps"]),
                                                    property=ast.Field(chain=["i"]),
                                                ),
                                                op=ast.ArithmeticOperationOp.Sub,
                                                right=ast.Constant(value=attribution_window_seconds),
                                            ),
                                        ),
                                    ]
                                ),
                            ),
                            ast.Field(chain=["utm_timestamps"]),
                        ],
                    ),
                ],
            ),
        )

    def _build_fallback_utm_expr(self, alias: str, utm_array_field: str) -> ast.Alias:
        """Build expression for fallback UTM data"""
        return ast.Alias(
            alias=alias,
            expr=ast.Call(
                name="if",
                args=[
                    ast.Call(
                        name="isNotNull",
                        args=[ast.Field(chain=["last_utm_timestamp"])],
                    ),
                    ast.ArrayAccess(
                        array=ast.Field(chain=[utm_array_field]),
                        property=ast.Call(
                            name="indexOf",
                            args=[
                                ast.Field(chain=["utm_timestamps"]),
                                ast.Field(chain=["last_utm_timestamp"]),
                            ],
                        ),
                    ),
                    ast.Constant(value=""),
                ],
            ),
        )

    def _build_attribution_logic_subquery(self, array_join_query: ast.SelectQuery) -> ast.SelectQuery:
        """Build subquery that applies attribution logic"""
        select_columns: list[ast.Expr] = [
            ast.Field(chain=["person_id"]),
            ast.Alias(
                alias="campaign_name",
                expr=self._build_attribution_expr("conversion_campaign", "fallback_campaign"),
            ),
            ast.Alias(
                alias="source_name",
                expr=self._build_attribution_expr("conversion_source", "fallback_source"),
            ),
            ast.Alias(
                alias="conversion_value",
                expr=self._get_final_conversion_value_expr(),
            ),
        ]

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=array_join_query),
        )

    def _build_attribution_expr(self, direct_field: str, fallback_field: str) -> ast.Call:
        """Build attribution expression with direct and fallback logic"""
        return ast.Call(
            name="if",
            args=[
                ast.Call(name="notEmpty", args=[ast.Field(chain=[direct_field])]),
                ast.Field(chain=[direct_field]),
                ast.Call(
                    name="if",
                    args=[
                        ast.Call(name="notEmpty", args=[ast.Field(chain=[fallback_field])]),
                        ast.Field(chain=[fallback_field]),
                        ast.Constant(value=""),
                    ],
                ),
            ],
        )

    def _get_final_conversion_value_expr(self) -> ast.Expr:
        """Get final conversion value expression for attribution logic"""
        math_type = self.goal.math

        if math_type in [BaseMathType.DAU, "dau"]:
            return ast.Field(chain=["person_id"])
        elif math_type in ["sum", PropertyMathType.SUM] or str(math_type).endswith("_sum"):
            return ast.Call(name="toFloat", args=[ast.Field(chain=["conversion_math_value"])])
        else:
            return ast.Constant(value=1)

    def _build_final_aggregation_query(self, attribution_query: ast.SelectQuery) -> ast.SelectQuery:
        """Build final aggregation query with organic defaults"""
        select_columns: list[ast.Expr] = [
            ast.Alias(
                alias=self.config.campaign_field,
                expr=self._build_organic_default_expr("campaign_name", self.config.organic_campaign),
            ),
            ast.Alias(
                alias=self.config.source_field,
                expr=self._build_organic_default_expr("source_name", self.config.organic_source),
            ),
            ast.Alias(
                alias=self.config.get_conversion_goal_column_name(self.index),
                expr=self._get_aggregation_expr(),
            ),
        ]

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=attribution_query, alias="attributed_conversions"),
            group_by=[ast.Field(chain=[field]) for field in self.config.group_by_fields],
        )

    def _build_organic_default_expr(self, field_name: str, default_value: str) -> ast.Call:
        """Build expression with organic default"""
        return ast.Call(
            name="if",
            args=[
                ast.Call(name="notEmpty", args=[ast.Field(chain=[field_name])]),
                ast.Field(chain=[field_name]),
                ast.Constant(value=default_value),
            ],
        )

    def _get_aggregation_expr(self) -> ast.Expr:
        """Get aggregation expression based on math type"""
        math_type = self.goal.math

        if math_type in [BaseMathType.DAU, "dau"]:
            # uniq() already returns 0 for no rows, no need for COALESCE
            return ast.Call(name="uniq", args=[ast.Field(chain=["person_id"])])
        elif math_type in ["sum", PropertyMathType.SUM] or str(math_type).endswith("_sum"):
            # sum() returns NULL for no rows, wrap with COALESCE to return 0
            sum_expr = ast.Call(name="sum", args=[ast.Field(chain=["conversion_value"])])
            return ast.Call(name="coalesce", args=[sum_expr, ast.Constant(value=0)])
        else:
            # count() already returns 0 for no rows, no need for COALESCE
            return ast.Call(name="count", args=[])

    def _generate_direct_query(self, additional_conditions: list[ast.Expr]) -> ast.SelectQuery:
        """Generate direct field access query for DataWarehouse nodes"""
        table = self.get_table_name()
        select_field = self.get_select_field()
        utm_campaign_expr, utm_source_expr = self.get_utm_expressions()

        # Build WHERE conditions
        where_conditions = self.get_base_where_conditions()
        where_conditions = add_conversion_goal_property_filters(where_conditions, self.goal, self.team)
        where_conditions.extend(additional_conditions)

        # Build SELECT columns with organic defaults
        select_columns: list[ast.Expr] = [
            ast.Alias(
                alias=self.config.campaign_field,
                expr=ast.Call(
                    name="coalesce", args=[utm_campaign_expr, ast.Constant(value=self.config.organic_campaign)]
                ),
            ),
            ast.Alias(
                alias=self.config.source_field,
                expr=ast.Call(name="coalesce", args=[utm_source_expr, ast.Constant(value=self.config.organic_source)]),
            ),
            ast.Alias(
                alias=self.config.get_conversion_goal_column_name(self.index),
                expr=select_field,
            ),
        ]

        # Build WHERE clause
        where_expr: Optional[ast.Expr] = None
        if where_conditions:
            where_expr = ast.And(exprs=where_conditions) if len(where_conditions) > 1 else where_conditions[0]

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=ast.Field(chain=[table])),
            where=where_expr,
            group_by=[ast.Field(chain=[field]) for field in self.config.group_by_fields],
        )

    def generate_cte_query_expr(self, additional_conditions: list[ast.Expr]) -> ast.Expr:
        """Generate CTE query expression"""
        cte_name = self.get_cte_name()
        select_query = self.generate_cte_query(additional_conditions)
        return ast.Alias(alias=cte_name, expr=select_query)

    def generate_join_clause(self, use_full_outer_join: bool = False) -> ast.JoinExpr:
        """Generate JOIN clause for this conversion goal"""
        cte_name = self.get_cte_name()
        alias = self.config.get_conversion_goal_alias(self.index)

        join_condition = ast.And(
            exprs=[
                ast.CompareOperation(
                    left=ast.Field(chain=self.config.get_campaign_cost_field_chain(self.config.campaign_field)),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Field(chain=[alias, self.config.campaign_field]),
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=self.config.get_campaign_cost_field_chain(self.config.source_field)),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Field(chain=[alias, self.config.source_field]),
                ),
            ]
        )

        join_type = "FULL OUTER JOIN" if use_full_outer_join else "LEFT JOIN"
        return ast.JoinExpr(
            join_type=join_type,
            table=ast.Field(chain=[cte_name]),
            alias=alias,
            constraint=ast.JoinConstraint(expr=join_condition, constraint_type="ON"),
        )

    def generate_select_columns(self) -> list[ast.Alias]:
        """Generate SELECT columns for this conversion goal"""
        goal_name = self.goal.conversion_goal_name
        alias_prefix = self.config.get_conversion_goal_alias(self.index)

        conversion_goal_field = ast.Field(chain=[alias_prefix, self.config.get_conversion_goal_column_name(self.index)])
        conversion_goal_alias = ast.Alias(alias=goal_name, expr=conversion_goal_field)

        # Cost per conversion calculation
        cost_field = ast.Field(chain=self.config.get_campaign_cost_field_chain(self.config.total_cost_field))
        goal_field = ast.Field(chain=[alias_prefix, self.config.get_conversion_goal_column_name(self.index)])

        cost_per_goal_expr = ast.Call(
            name="round",
            args=[
                ast.ArithmeticOperation(
                    left=cost_field,
                    op=ast.ArithmeticOperationOp.Div,
                    right=ast.Call(name="nullif", args=[goal_field, ast.Constant(value=0)]),
                ),
                ast.Constant(value=self.config.decimal_precision),
            ],
        )

        cost_per_goal_alias = ast.Alias(
            alias=f"{self.config.cost_per_prefix} {goal_name}",
            expr=cost_per_goal_expr,
        )

        return [conversion_goal_alias, cost_per_goal_alias]

    def _ensure_datetime_call(self, date_expr: ast.Expr) -> ast.Expr:
        """Convert toDate to toDateTime for proper date handling"""
        if isinstance(date_expr, ast.Call) and date_expr.name == "toDate":
            return ast.Call(name="toDateTime", args=date_expr.args)
        return date_expr

    def _is_date_condition(self, condition: ast.Expr) -> bool:
        """Check if condition filters on timestamp fields"""

        def has_timestamp_field(expr: ast.Expr) -> bool:
            if isinstance(expr, ast.Field):
                return "timestamp" in expr.chain
            elif isinstance(expr, ast.CompareOperation):
                return has_timestamp_field(expr.left) or has_timestamp_field(expr.right)
            elif isinstance(expr, ast.Call):
                return any(has_timestamp_field(arg) for arg in expr.args)
            return False

        return has_timestamp_field(condition)

    def _is_event_condition(self, condition: ast.Expr, conversion_event: Optional[str]) -> bool:
        """Check if condition filters on event types that we handle explicitly"""
        # For ActionsNode, we need to check if this is an action condition
        if self.goal.kind == "ActionsNode" and conversion_event is None:
            # Check if this condition comes from action_to_expr (complex action conditions)
            # Action conditions can be complex AST expressions, not just simple event comparisons
            # We identify them by checking if they're in our base conditions
            base_conditions = self.get_base_where_conditions()
            for base_condition in base_conditions:
                if condition == base_condition:
                    return True

        if isinstance(condition, ast.CompareOperation):
            if (
                isinstance(condition.left, ast.Field)
                and condition.left.chain == ["events", "event"]
                and condition.op == ast.CompareOperationOp.Eq
                and isinstance(condition.right, ast.Constant)
            ):
                event_value = condition.right.value
                # Only consider it an "event condition we handle" if it's related to our conversion logic
                return event_value == conversion_event or event_value == "$pageview"

        return False


def add_conversion_goal_property_filters(
    conditions: list[ast.Expr],
    conversion_goal: ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3,
    team: Team,
) -> list[ast.Expr]:
    """Add property filters for conversion goals"""
    conversion_goal_properties = conversion_goal.properties
    if conversion_goal_properties:
        property_expr = property_to_expr(conversion_goal_properties, team=team, scope="event")
        if property_expr:
            conditions.append(property_expr)

    return conditions
