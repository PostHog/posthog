# Marketing Analytics Utility Functions

from dataclasses import dataclass
from typing import Any
import structlog

from posthog.hogql.property import property_to_expr, action_to_expr
from posthog.hogql.printer import to_printed_hogql
from posthog.models import Action
from posthog.schema import BaseMathType, PropertyMathType

logger = structlog.get_logger(__name__)


def get_marketing_analytics_columns_with_conversion_goals(conversion_goals: list) -> list[str]:
    """Get column names including conversion goals"""
    from .constants import DEFAULT_MARKETING_ANALYTICS_COLUMNS
    
    columns = DEFAULT_MARKETING_ANALYTICS_COLUMNS.copy()
    
    for index, conversion_goal in enumerate(conversion_goals):
        goal_name = getattr(conversion_goal, 'conversion_goal_name', f'Goal {index + 1}')
        columns.append(goal_name)
        columns.append(f"Cost per {goal_name}")
    
    return columns


def get_source_map_field(source_map, field_name, fallback=None):
    """Helper to safely get field from source_map regardless of type"""
    if hasattr(source_map, field_name):
        return getattr(source_map, field_name, fallback)
    elif hasattr(source_map, 'get'):
        return source_map.get(field_name, fallback)
    else:
        return fallback


def get_marketing_config_value(config, key, default=None):
    """Safely extract value from marketing config regardless of type"""
    if not config:
        return default
    
    if hasattr(config, key):
        return getattr(config, key, default)
    elif hasattr(config, 'get'):
        return config.get(key, default)
    else:
        try:
            return dict(config).get(key, default)
        except (TypeError, AttributeError):
            return default


@dataclass
class ConversionGoalProcessor:
    """Handles conversion goal processing logic"""
    goal: Any
    index: int
    team: Any
    query_date_range: Any
    
    def get_cte_name(self):
        """Generate CTE name for conversion goal"""
        goal_name = getattr(self.goal, 'conversion_goal_name', f'goal_{self.index}')
        sanitized_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in goal_name)
        return f"cg_{self.index}_{sanitized_name}"
    
    def get_table_name(self):
        """Get table name for conversion goal"""
        name = getattr(self.goal, 'name', None)
        kind = getattr(self.goal, 'kind', None)
        
        if not name:
            return 'events'
        
        if kind == "EventsNode":
            return 'events'
        elif kind == "ActionsNode":
            return 'events'
        elif kind == "DataWarehouseNode":
            return getattr(self.goal, 'table_name', 'events')
        else:
            return 'events'
    
    def get_schema_fields(self):
        """Get schema fields from conversion goal"""
        schema = {}
        if hasattr(self.goal, 'schema_'):
            schema = self.goal.schema_ or {}
        elif hasattr(self.goal, 'model_dump'):
            model_data = self.goal.model_dump()
            schema = model_data.get('schema', {})
        
        return {
            'utm_campaign_field': schema.get('utm_campaign_name') or 'utm_campaign',
            'utm_source_field': schema.get('utm_source_name') or 'utm_source',
            'timestamp_field': schema.get('timestamp_field')
        }
    
    def get_utm_expressions(self):
        """Get UTM campaign and source expressions based on node kind"""
        kind = getattr(self.goal, 'kind', None)
        schema_fields = self.get_schema_fields()
        
        if kind in ["EventsNode", "ActionsNode"]:
            property_prefix = "properties."
            utm_campaign_expr = f"{property_prefix}{schema_fields['utm_campaign_field']}"
            utm_source_expr = f"{property_prefix}{schema_fields['utm_source_field']}"
        else:
            utm_campaign_expr = schema_fields['utm_campaign_field']
            utm_source_expr = schema_fields['utm_source_field']
        
        return utm_campaign_expr, utm_source_expr
    
    def get_select_field(self):
        """Get the select field based on math type and node kind"""
        math_type = getattr(self.goal, 'math', None)
        kind = getattr(self.goal, 'kind', None)
        schema_fields = self.get_schema_fields()
        
        # Handle different math types
        if math_type in [BaseMathType.DAU, "dau"]:
            if kind == "EventsNode":
                select_field = "count(distinct distinct_id)"
            elif kind == "DataWarehouseNode":
                distinct_id_field = schema_fields.get('distinct_id_field', 'distinct_id')
                select_field = f"count(distinct {distinct_id_field})"
            else:
                select_field = "count(distinct distinct_id)"
        elif math_type == "sum" or str(math_type).endswith("_sum") or math_type == PropertyMathType.SUM:
            math_property = getattr(self.goal, 'math_property', None)
            if not math_property:
                select_field = "0"
            else:
                if kind == "EventsNode":
                    select_field = f"sum(toFloat(JSONExtractRaw(properties, '{math_property}')))"
                elif kind == "DataWarehouseNode":
                    select_field = f"sum(toFloat({math_property}))"
                else:
                    select_field = f"sum(toFloat(JSONExtractRaw(properties, '{math_property}')))"
        else:
            select_field = "count(*)"

        return select_field
    
    def get_base_where_conditions(self):
        """Get base WHERE conditions for the conversion goal"""
        kind = getattr(self.goal, 'kind', None)
        conditions = []
        
        # Add event filter for EventsNode
        if kind == "EventsNode":
            conditions.append(f"team_id = {self.team.pk}")
            event_name = getattr(self.goal, 'event', None)
            if event_name:
                conditions.append(f"event = '{event_name}'")
            else:
                conditions.append("1=1")
        elif kind == "ActionsNode":
            conditions.append(f"team_id = {self.team.pk}")
            # Handle ActionsNode by converting action to HogQL expression
            action_id = getattr(self.goal, 'id', None)
            if action_id:
                try:
                    action = Action.objects.get(pk=int(action_id), team__project_id=self.team.project_id)
                    
                    try:
                        action_expr = action_to_expr(action)
                        action_condition = to_printed_hogql(action_expr, self.team)
                        conditions.append(action_condition)
                    except Exception:
                        # Fallback: use basic event filter if action has steps
                        action_steps = action.steps.all() if hasattr(action.steps, 'all') else action.steps
                        if action_steps:
                            first_step = action_steps[0]
                            if hasattr(first_step, 'event') and first_step.event:
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
        elif kind == "DataWarehouseNode":
            conditions.append("1=1")
        
        return conditions
    
    def get_date_field(self):
        """Get the appropriate date field for the conversion goal"""
        kind = getattr(self.goal, 'kind', None)
        schema_fields = self.get_schema_fields()
        
        if kind == "DataWarehouseNode":
            return schema_fields['timestamp_field'] or 'timestamp'
        else:
            return 'timestamp'


def add_conversion_goal_property_filters(conditions, conversion_goal, team):
    """Add conversion goal specific property filters to conditions"""
    conversion_goal_properties = getattr(conversion_goal, 'properties', [])
    if conversion_goal_properties:
        try:
            property_expr = property_to_expr(conversion_goal_properties, team=team, scope="event")
            if property_expr:
                property_condition = to_printed_hogql(property_expr, team)
                conditions.append(f"({property_condition})")
        except Exception as e:
            logger.error("Error applying property filters to conversion goal", error=str(e))
    return conditions


def get_global_property_conditions(query, team):
    """Extract global property filter conditions"""
    conditions = []
    global_properties = getattr(query, 'properties', [])
    if global_properties and isinstance(global_properties, list) and len(global_properties) > 0:
        try:
            global_property_expr = property_to_expr(global_properties, team=team, scope="event")
            if global_property_expr:
                global_property_condition = to_printed_hogql(global_property_expr, team)
                conditions.append(f"({global_property_condition})")
        except (IndexError, TypeError, AttributeError):
            pass
        except Exception as e:
            logger.error("Error applying global property filters", error=str(e))
    return conditions 