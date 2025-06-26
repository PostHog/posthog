from dataclasses import dataclass
from typing import Any
import structlog

from posthog.hogql.property import property_to_expr, action_to_expr
from posthog.hogql.printer import to_printed_hogql
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

    def get_utm_expressions(self):
        """Get UTM campaign and source expressions based on node kind"""
        kind = getattr(self.goal, "kind", None)
        schema_fields = self.get_schema_fields()

        if kind in [NodeKind.EVENTS_NODE, NodeKind.ACTIONS_NODE]:
            property_prefix = "properties."
            utm_campaign_expr = f"{property_prefix}{schema_fields['utm_campaign_field']}"
            utm_source_expr = f"{property_prefix}{schema_fields['utm_source_field']}"
        else:
            utm_campaign_expr = schema_fields["utm_campaign_field"]
            utm_source_expr = schema_fields["utm_source_field"]

        return utm_campaign_expr, utm_source_expr

    def get_select_field(self):
        """Get the select field based on math type and node kind"""
        math_type = getattr(self.goal, "math", None)
        kind = getattr(self.goal, "kind", None)
        schema_fields = self.get_schema_fields()

        # Handle different math types
        if math_type in [BaseMathType.DAU, "dau"]:
            if kind == NodeKind.EVENTS_NODE:
                select_field = "count(distinct distinct_id)"
            elif kind == NodeKind.DATA_WAREHOUSE_NODE:
                distinct_id_field = schema_fields.get("distinct_id_field", "distinct_id")
                select_field = f"count(distinct {distinct_id_field})"
            else:
                select_field = "count(distinct distinct_id)"
        elif math_type == "sum" or str(math_type).endswith("_sum") or math_type == PropertyMathType.SUM:
            math_property = getattr(self.goal, "math_property", None)
            if not math_property:
                select_field = "0"
            else:
                if kind == NodeKind.EVENTS_NODE:
                    select_field = (
                        f"round(sum(toFloat(JSONExtractRaw(properties, '{math_property}'))), {DECIMAL_PRECISION})"
                    )
                elif kind == NodeKind.DATA_WAREHOUSE_NODE:
                    select_field = f"round(sum(toFloat({math_property})), {DECIMAL_PRECISION})"
                else:
                    select_field = (
                        f"round(sum(toFloat(JSONExtractRaw(properties, '{math_property}'))), {DECIMAL_PRECISION})"
                    )
        else:
            select_field = "count(*)"

        return select_field

    def get_base_where_conditions(self):
        """Get base WHERE conditions for the conversion goal"""
        kind = getattr(self.goal, "kind", None)
        conditions = []

        # Add event filter for EventsNode
        if kind == NodeKind.EVENTS_NODE:
            conditions.append(f"team_id = {self.team.pk}")
            event_name = getattr(self.goal, "event", None)
            if event_name:
                conditions.append(f"event = '{event_name}'")
            else:
                conditions.append("1=1")
        elif kind == NodeKind.ACTIONS_NODE:
            conditions.append(f"team_id = {self.team.pk}")
            # Handle ActionsNode by converting action to HogQL expression
            action_id = getattr(self.goal, "id", None)
            if action_id:
                try:
                    action = Action.objects.get(pk=int(action_id), team__project_id=self.team.project_id)

                    try:
                        action_expr = action_to_expr(action)
                        action_condition = to_printed_hogql(action_expr, self.team)
                        conditions.append(action_condition)
                    except Exception:
                        # Fallback: use basic event filter if action has steps
                        action_steps = action.steps.all() if hasattr(action.steps, "all") else action.steps
                        if action_steps:
                            first_step = action_steps[0]
                            if hasattr(first_step, "event") and first_step.event:
                                conditions.append(f"event = '{first_step.event}'")
                            else:
                                conditions.append("1=0")
                        else:
                            conditions.append("1=0")
                except Action.DoesNotExist:
                    conditions.append("1=0")
                except Exception:
                    conditions.append("1=0")
            else:
                conditions.append("1=0")
        elif kind == NodeKind.DATA_WAREHOUSE_NODE:
            conditions.append("1=1")

        return conditions

    def get_date_field(self):
        """Get the appropriate date field for the conversion goal"""
        kind = getattr(self.goal, "kind", None)
        schema_fields = self.get_schema_fields()

        if kind == NodeKind.DATA_WAREHOUSE_NODE:
            return schema_fields["timestamp_field"] or "timestamp"
        else:
            return "timestamp"

    def generate_cte_query(self, additional_conditions: list | None = None) -> str:
        """Generate the complete CTE query for this conversion goal"""
        from .constants import UNKNOWN_CAMPAIGN, UNKNOWN_SOURCE

        # Get all required components
        cte_name = self.get_cte_name()
        table = self.get_table_name()
        select_field = self.get_select_field()
        utm_campaign_expr, utm_source_expr = self.get_utm_expressions()

        # Build WHERE conditions
        where_conditions = self.get_base_where_conditions()

        # Apply conversion goal specific property filters
        where_conditions = add_conversion_goal_property_filters(where_conditions, self.goal, self.team)

        # Add any additional conditions (like date range and global filters)
        if additional_conditions:
            where_conditions.extend(additional_conditions)

        # Build the CTE query
        cte_query = f"""
{cte_name} AS (
    SELECT
        coalesce({utm_campaign_expr}, '{UNKNOWN_CAMPAIGN}') as {MarketingSourceAdapter.campaign_name_field},
        coalesce({utm_source_expr}, '{UNKNOWN_SOURCE}') as {MarketingSourceAdapter.source_name_field},
        {select_field} as {CONVERSION_GOAL_PREFIX}{self.index}
    FROM {table}
    WHERE {' AND '.join(where_conditions)}
    GROUP BY {MarketingSourceAdapter.campaign_name_field}, {MarketingSourceAdapter.source_name_field}
)"""

        return cte_query.strip()

    def generate_join_clause(self) -> str:
        """Generate the JOIN clause for this conversion goal"""
        cte_name = self.get_cte_name()
        return f"""LEFT JOIN {cte_name} {CONVERSION_GOAL_PREFIX_ABBREVIATION}{self.index} ON {CAMPAIGN_COST_CTE_NAME}.{MarketingSourceAdapter.campaign_name_field} = {CONVERSION_GOAL_PREFIX_ABBREVIATION}{self.index}.{MarketingSourceAdapter.campaign_name_field}
    AND {CAMPAIGN_COST_CTE_NAME}.{MarketingSourceAdapter.source_name_field} = {CONVERSION_GOAL_PREFIX_ABBREVIATION}{self.index}.{MarketingSourceAdapter.source_name_field}"""

    def generate_select_columns(self) -> list[str]:
        """Generate the SELECT columns for this conversion goal"""
        goal_name = getattr(self.goal, "conversion_goal_name", f"Goal {self.index + 1}")

        return [
            f'    {CONVERSION_GOAL_PREFIX_ABBREVIATION}{self.index}.{CONVERSION_GOAL_PREFIX}{self.index} as "{goal_name}"',
            f'    round({CAMPAIGN_COST_CTE_NAME}.{TOTAL_COST_FIELD} / nullif({CONVERSION_GOAL_PREFIX_ABBREVIATION}{self.index}.{CONVERSION_GOAL_PREFIX}{self.index}, 0), {DECIMAL_PRECISION}) as "Cost per {goal_name}"',
        ]


def add_conversion_goal_property_filters(conditions, conversion_goal, team):
    """Add conversion goal specific property filters to conditions"""
    conversion_goal_properties = getattr(conversion_goal, "properties", [])
    if conversion_goal_properties:
        try:
            property_expr = property_to_expr(conversion_goal_properties, team=team, scope="event")
            if property_expr:
                property_condition = to_printed_hogql(property_expr, team)
                conditions.append(f"({property_condition})")
        except Exception as e:
            logger.exception("Error applying property filters to conversion goal", error=str(e))
    return conditions
