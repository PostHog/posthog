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
)

logger = structlog.get_logger(__name__)


@dataclass
class ConversionGoalProcessor:
    """Handles conversion goal processing logic"""

    goal: Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3]
    index: int
    team: Team
    query_date_range: DateRange | None

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
            # For events: properties.utm_campaign, properties.utm_source
            utm_campaign_expr = ast.Field(chain=["properties", utm_campaign_field])
            utm_source_expr = ast.Field(chain=["properties", utm_source_field])
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
            if self.goal.kind == "EventsNode":
                # uniq(distinct_id)
                return ast.Call(name="uniq", args=[ast.Field(chain=["distinct_id"])])
            elif self.goal.kind == "DataWarehouseNode":
                distinct_id_field = self.goal.schema_map.get("distinct_id_field", "distinct_id")
                return ast.Call(name="uniq", args=[ast.Field(chain=[distinct_id_field])])
            else:
                return ast.Call(name="uniq", args=[ast.Field(chain=["distinct_id"])])
        elif math_type == "sum" or str(math_type).endswith("_sum") or math_type == PropertyMathType.SUM:
            math_property = self.goal.math_property
            if not math_property:
                return ast.Constant(value=0)
            else:
                if self.goal.kind == "EventsNode":
                    # round(sum(toFloat(JSONExtractRaw(properties, 'math_property'))), DECIMAL_PRECISION)
                    json_extract = ast.Call(
                        name="JSONExtractRaw", args=[ast.Field(chain=["properties"]), ast.Constant(value=math_property)]
                    )
                    to_float = ast.Call(name="toFloat", args=[json_extract])
                    sum_expr = ast.Call(name="sum", args=[to_float])
                    return ast.Call(name="round", args=[sum_expr, ast.Constant(value=DECIMAL_PRECISION)])
                elif self.goal.kind == "DataWarehouseNode":
                    # round(sum(toFloat(math_property)), DECIMAL_PRECISION)
                    to_float = ast.Call(name="toFloat", args=[ast.Field(chain=[math_property])])
                    sum_expr = ast.Call(name="sum", args=[to_float])
                    return ast.Call(name="round", args=[sum_expr, ast.Constant(value=DECIMAL_PRECISION)])
                else:
                    # Same as events node
                    json_extract = ast.Call(
                        name="JSONExtractRaw", args=[ast.Field(chain=["properties"]), ast.Constant(value=math_property)]
                    )
                    to_float = ast.Call(name="toFloat", args=[json_extract])
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
            # team_id = {self.team.pk}
            team_condition = ast.CompareOperation(
                left=ast.Field(chain=["team_id"]), op=ast.CompareOperationOp.Eq, right=ast.Constant(value=self.team.pk)
            )
            conditions.append(team_condition)

            event_name = self.goal.event
            if event_name:
                # event = 'event_name'
                event_condition = ast.CompareOperation(
                    left=ast.Field(chain=["event"]), op=ast.CompareOperationOp.Eq, right=ast.Constant(value=event_name)
                )
                conditions.append(event_condition)
        elif self.goal.kind == "ActionsNode":
            # team_id = {self.team.pk}
            team_condition = ast.CompareOperation(
                left=ast.Field(chain=["team_id"]), op=ast.CompareOperationOp.Eq, right=ast.Constant(value=self.team.pk)
            )
            conditions.append(team_condition)

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
            return "timestamp"

    def generate_cte_query(self, additional_conditions: list[ast.Expr]) -> ast.SelectQuery:
        """Generate the complete CTE query for this conversion goal"""
        from .constants import UNKNOWN_CAMPAIGN, UNKNOWN_SOURCE

        # Get all required components
        table = self.get_table_name()
        select_field = self.get_select_field()
        utm_campaign_expr, utm_source_expr = self.get_utm_expressions()

        # Build WHERE conditions
        where_conditions = self.get_base_where_conditions()

        # Apply conversion goal specific property filters
        where_conditions = add_conversion_goal_property_filters(where_conditions, self.goal, self.team)

        where_conditions.extend(additional_conditions)

        # Build coalesce expressions for UTM fields
        campaign_coalesce = ast.Call(name="coalesce", args=[utm_campaign_expr, ast.Constant(value=UNKNOWN_CAMPAIGN)])
        source_coalesce = ast.Call(name="coalesce", args=[utm_source_expr, ast.Constant(value=UNKNOWN_SOURCE)])

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
