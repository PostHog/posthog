from dataclasses import dataclass
from typing import Any
import structlog

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr, action_to_expr
from posthog.models import Action
from posthog.schema import BaseMathType, NodeKind, PropertyMathType
from .adapters.base import MarketingSourceAdapter
from .utils import sanitize_conversion_goal_name
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

    goal: Any
    index: int
    team: Any
    query_date_range: Any

    def get_cte_name(self):
        """Generate CTE name for conversion goal"""
        goal_name = getattr(self.goal, "conversion_goal_name", f"goal_{self.index}")
        sanitized_name = sanitize_conversion_goal_name(goal_name)
        return f"{CONVERSION_GOAL_PREFIX_ABBREVIATION}{self.index}_{sanitized_name}"

    def get_table_name(self):
        """Get table name for conversion goal"""
        name = getattr(self.goal, "name", None)
        kind = getattr(self.goal, "kind", None)

        if not name:
            return "events"

        if kind == NodeKind.EVENTS_NODE:
            return "events"
        elif kind == NodeKind.ACTIONS_NODE:
            return "events"
        elif kind == NodeKind.DATA_WAREHOUSE_NODE:
            return getattr(self.goal, "table_name", "events")
        else:
            return "events"

    def get_schema_fields(self):
        """Get schema fields from conversion goal"""
        schema = {}
        if hasattr(self.goal, "schema_"):
            schema = self.goal.schema_ or {}
        elif hasattr(self.goal, "model_dump"):
            model_data = self.goal.model_dump()
            schema = model_data.get("schema", {})

        # TODO: these strings should be constants and not hardcoded
        return {
            "utm_campaign_field": schema.get("utm_campaign_name") or "utm_campaign",
            "utm_source_field": schema.get("utm_source_name") or "utm_source",
            "timestamp_field": schema.get("timestamp_field"),
        }

    def get_utm_expressions(self) -> tuple[ast.Expr, ast.Expr]:
        """Get UTM campaign and source expressions as AST based on node kind"""
        kind = getattr(self.goal, "kind", None)
        schema_fields = self.get_schema_fields()

        if kind in [NodeKind.EVENTS_NODE, NodeKind.ACTIONS_NODE]:
            # For events: properties.utm_campaign, properties.utm_source
            utm_campaign_expr = ast.Field(chain=["properties", schema_fields['utm_campaign_field']])
            utm_source_expr = ast.Field(chain=["properties", schema_fields['utm_source_field']])
        else:
            # For data warehouse: direct field access
            utm_campaign_expr = ast.Field(chain=[schema_fields["utm_campaign_field"]])
            utm_source_expr = ast.Field(chain=[schema_fields["utm_source_field"]])

        return utm_campaign_expr, utm_source_expr

    def get_select_field(self) -> ast.Expr:
        """Get the select field based on math type and node kind"""
        math_type = getattr(self.goal, "math", None)
        kind = getattr(self.goal, "kind", None)
        schema_fields = self.get_schema_fields()

        # Handle different math types
        if math_type in [BaseMathType.DAU, "dau"]:
            if kind == NodeKind.EVENTS_NODE:
                # uniq(distinct_id)
                return ast.Call(
                    name="uniq",
                    args=[ast.Field(chain=["distinct_id"])]
                )
            elif kind == NodeKind.DATA_WAREHOUSE_NODE:
                distinct_id_field = schema_fields.get("distinct_id_field", "distinct_id")
                return ast.Call(
                    name="uniq",
                    args=[ast.Field(chain=[distinct_id_field])]
                )
            else:
                return ast.Call(
                    name="uniq",
                    args=[ast.Field(chain=["distinct_id"])]
                )
        elif math_type == "sum" or str(math_type).endswith("_sum") or math_type == PropertyMathType.SUM:
            math_property = getattr(self.goal, "math_property", None)
            if not math_property:
                return ast.Constant(value=0)
            else:
                if kind == NodeKind.EVENTS_NODE:
                    # round(sum(toFloat(JSONExtractRaw(properties, 'math_property'))), DECIMAL_PRECISION)
                    json_extract = ast.Call(
                        name="JSONExtractRaw",
                        args=[ast.Field(chain=["properties"]), ast.Constant(value=math_property)]
                    )
                    to_float = ast.Call(name="toFloat", args=[json_extract])
                    sum_expr = ast.Call(name="sum", args=[to_float])
                    return ast.Call(name="round", args=[sum_expr, ast.Constant(value=DECIMAL_PRECISION)])
                elif kind == NodeKind.DATA_WAREHOUSE_NODE:
                    # round(sum(toFloat(math_property)), DECIMAL_PRECISION)
                    to_float = ast.Call(name="toFloat", args=[ast.Field(chain=[math_property])])
                    sum_expr = ast.Call(name="sum", args=[to_float])
                    return ast.Call(name="round", args=[sum_expr, ast.Constant(value=DECIMAL_PRECISION)])
                else:
                    # Same as events node
                    json_extract = ast.Call(
                        name="JSONExtractRaw",
                        args=[ast.Field(chain=["properties"]), ast.Constant(value=math_property)]
                    )
                    to_float = ast.Call(name="toFloat", args=[json_extract])
                    sum_expr = ast.Call(name="sum", args=[to_float])
                    return ast.Call(name="round", args=[sum_expr, ast.Constant(value=DECIMAL_PRECISION)])
        else:
            # count(*)
            return ast.Call(name="count", args=[ast.Constant(value="*")])

    def get_base_where_conditions(self) -> list[ast.Expr]:
        """Get base WHERE conditions for the conversion goal"""
        kind = getattr(self.goal, "kind", None)
        conditions = []

        # Add event filter for EventsNode
        if kind == NodeKind.EVENTS_NODE:
            # team_id = {self.team.pk}
            team_condition = ast.CompareOperation(
                left=ast.Field(chain=["team_id"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=self.team.pk)
            )
            conditions.append(team_condition)
            
            event_name = getattr(self.goal, "event", None)
            if event_name:
                # event = 'event_name'
                event_condition = ast.CompareOperation(
                    left=ast.Field(chain=["event"]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value=event_name)
                )
                conditions.append(event_condition)
            else:
                # 1=1 (always true)
                conditions.append(ast.CompareOperation(
                    left=ast.Constant(value=1),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value=1)
                ))
        elif kind == NodeKind.ACTIONS_NODE:
            # team_id = {self.team.pk}
            team_condition = ast.CompareOperation(
                left=ast.Field(chain=["team_id"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=self.team.pk)
            )
            conditions.append(team_condition)
            
            # Handle ActionsNode by converting action to HogQL expression
            action_id = getattr(self.goal, "id", None)
            if action_id:
                try:
                    action = Action.objects.get(pk=int(action_id), team__project_id=self.team.project_id)

                    try:
                        action_expr = action_to_expr(action)
                        conditions.append(action_expr)
                    except Exception:
                        # Fallback: use basic event filter if action has steps
                        action_steps = action.steps.all() if hasattr(action.steps, "all") else action.steps
                        if action_steps:
                            first_step = action_steps[0]
                            if hasattr(first_step, "event") and first_step.event:
                                # event = 'first_step.event'
                                event_condition = ast.CompareOperation(
                                    left=ast.Field(chain=["event"]),
                                    op=ast.CompareOperationOp.Eq,
                                    right=ast.Constant(value=first_step.event)
                                )
                                conditions.append(event_condition)
                            else:
                                # 1=0 (always false)
                                conditions.append(ast.CompareOperation(
                                    left=ast.Constant(value=1),
                                    op=ast.CompareOperationOp.Eq,
                                    right=ast.Constant(value=0)
                                ))
                        else:
                            # 1=0 (always false)
                            conditions.append(ast.CompareOperation(
                                left=ast.Constant(value=1),
                                op=ast.CompareOperationOp.Eq,
                                right=ast.Constant(value=0)
                            ))
                except Action.DoesNotExist:
                    # 1=0 (always false)
                    conditions.append(ast.CompareOperation(
                        left=ast.Constant(value=1),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value=0)
                    ))
                except Exception:
                    # 1=0 (always false)
                    conditions.append(ast.CompareOperation(
                        left=ast.Constant(value=1),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value=0)
                    ))
            else:
                # 1=0 (always false)
                conditions.append(ast.CompareOperation(
                    left=ast.Constant(value=1),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value=0)
                ))
        elif kind == NodeKind.DATA_WAREHOUSE_NODE:
            # 1=1 (always true)
            conditions.append(ast.CompareOperation(
                left=ast.Constant(value=1),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=1)
            ))

        return conditions

    def get_date_field(self):
        """Get the appropriate date field for the conversion goal"""
        kind = getattr(self.goal, "kind", None)
        schema_fields = self.get_schema_fields()

        if kind == NodeKind.DATA_WAREHOUSE_NODE:
            return schema_fields["timestamp_field"] or "timestamp"
        else:
            return "timestamp"

    def generate_cte_query(self, additional_conditions: list[ast.Expr]) -> str:
        """Generate the complete CTE query for this conversion goal"""
        from .constants import UNKNOWN_CAMPAIGN, UNKNOWN_SOURCE

        # Get all required components as AST
        cte_name = self.get_cte_name()
        table = self.get_table_name()
        select_field_ast = self.get_select_field()
        utm_campaign_expr_ast, utm_source_expr_ast = self.get_utm_expressions()

        # Build WHERE conditions as AST
        where_conditions_ast = self.get_base_where_conditions()

        # Apply conversion goal specific property filters (returns AST)
        where_conditions_ast = add_conversion_goal_property_filters(where_conditions_ast, self.goal, self.team)

        where_conditions_ast.extend(additional_conditions)

        # Build coalesce expressions for UTM fields as AST
        campaign_coalesce_ast = ast.Call(
            name="coalesce",
            args=[utm_campaign_expr_ast, ast.Constant(value=UNKNOWN_CAMPAIGN)]
        )
        source_coalesce_ast = ast.Call(
            name="coalesce", 
            args=[utm_source_expr_ast, ast.Constant(value=UNKNOWN_SOURCE)]
        )

        # Convert to HogQL only at the end
        campaign_select = campaign_coalesce_ast.to_hogql()
        source_select = source_coalesce_ast.to_hogql()
        value_select = select_field_ast.to_hogql()
        where_clause = ' AND '.join(cond.to_hogql() for cond in where_conditions_ast)

        # Build the CTE query
        cte_query = f"""
{cte_name} AS (
    SELECT
        {campaign_select} as {MarketingSourceAdapter.campaign_name_field},
        {source_select} as {MarketingSourceAdapter.source_name_field},
        {value_select} as {CONVERSION_GOAL_PREFIX}{self.index}
    FROM {table}
    WHERE {where_clause}
    GROUP BY {MarketingSourceAdapter.campaign_name_field}, {MarketingSourceAdapter.source_name_field}
)"""

        return cte_query.strip()

    def generate_join_clause(self) -> str:
        """Generate the JOIN clause for this conversion goal"""
        cte_name = self.get_cte_name()
        return """LEFT JOIN {} {} ON {}.{} = {}.{}
    AND {}.{} = {}.{}""".format(
            cte_name, 
            CONVERSION_GOAL_PREFIX_ABBREVIATION + str(self.index),
            CAMPAIGN_COST_CTE_NAME,
            MarketingSourceAdapter.campaign_name_field,
            CONVERSION_GOAL_PREFIX_ABBREVIATION + str(self.index),
            MarketingSourceAdapter.campaign_name_field,
            CAMPAIGN_COST_CTE_NAME,
            MarketingSourceAdapter.source_name_field,
            CONVERSION_GOAL_PREFIX_ABBREVIATION + str(self.index),
            MarketingSourceAdapter.source_name_field
        )

    def generate_select_columns(self) -> list[str]:
        """Generate the SELECT columns for this conversion goal"""
        goal_name = getattr(self.goal, "conversion_goal_name", f"Goal {self.index + 1}")

        return [
            '    {}.{} as "{}"'.format(
                CONVERSION_GOAL_PREFIX_ABBREVIATION + str(self.index),
                CONVERSION_GOAL_PREFIX + str(self.index),
                goal_name
            ),
            '    round({}.{} / nullif({}.{}, 0), {}) as "Cost per {}"'.format(
                CAMPAIGN_COST_CTE_NAME,
                TOTAL_COST_FIELD,
                CONVERSION_GOAL_PREFIX_ABBREVIATION + str(self.index),
                CONVERSION_GOAL_PREFIX + str(self.index),
                DECIMAL_PRECISION,
                goal_name
            ),
        ]


def add_conversion_goal_property_filters(conditions, conversion_goal, team) -> list[str]:
    """Add conversion goal specific property filters to conditions"""
    conversion_goal_properties = getattr(conversion_goal, "properties", [])
    if conversion_goal_properties:
        try:
            property_expr = property_to_expr(conversion_goal_properties, team=team, scope="event")
            if property_expr:
                conditions.append(property_expr)
        except Exception as e:
            logger.exception("Error applying property filters to conversion goal", error=str(e))
    return conditions
