# Marketing Analytics Utility Functions

import structlog

from posthog.hogql.property import property_to_expr
from posthog.hogql.printer import to_printed_hogql
from posthog.schema import NodeKind
from posthog.schema import ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3

from .constants import DEFAULT_MARKETING_ANALYTICS_COLUMNS

logger = structlog.get_logger(__name__)


def get_marketing_analytics_columns_with_conversion_goals(conversion_goals: list) -> list[str]:
    """Get column names including conversion goals"""

    columns = DEFAULT_MARKETING_ANALYTICS_COLUMNS.copy()

    for index, conversion_goal in enumerate(conversion_goals):
        goal_name = getattr(conversion_goal, "conversion_goal_name", f"Goal {index + 1}")
        columns.append(goal_name)
        columns.append(f"Cost per {goal_name}")

    return columns


def get_source_map_field(source_map, field_name, fallback=None):
    """Helper to safely get field from source_map regardless of type"""
    if hasattr(source_map, field_name):
        return getattr(source_map, field_name, fallback)
    elif hasattr(source_map, "get"):
        return source_map.get(field_name, fallback)
    else:
        return fallback


def get_marketing_config_value(config, key, default=None):
    """Safely extract value from marketing config regardless of type"""
    if not config:
        return default

    if hasattr(config, key):
        return getattr(config, key, default)
    elif hasattr(config, "get"):
        return config.get(key, default)
    else:
        try:
            return dict(config).get(key, default)
        except (TypeError, AttributeError):
            return default


def get_global_property_conditions(query, team):
    """Extract global property filter conditions"""
    conditions = []
    global_properties = getattr(query, "properties", [])
    if global_properties and isinstance(global_properties, list) and len(global_properties) > 0:
        try:
            global_property_expr = property_to_expr(global_properties, team=team, scope="event")
            if global_property_expr:
                global_property_condition = to_printed_hogql(global_property_expr, team)
                conditions.append(f"({global_property_condition})")
        except (IndexError, TypeError, AttributeError):
            pass
        except Exception as e:
            logger.exception("Error applying global property filters", error=str(e))
    return conditions


def convert_team_conversion_goals_to_objects(team_conversion_goals, team_pk):
    """Convert team conversion goals from dict format to ConversionGoalFilter objects"""

    logger = structlog.get_logger(__name__)
    converted_goals = []

    for goal in team_conversion_goals:
        try:
            # Handle both dict and object formats
            if hasattr(goal, "get"):
                goal_dict = dict(goal) if hasattr(goal, "items") else goal
            elif hasattr(goal, "__dict__"):
                goal_dict = goal.__dict__
            else:
                goal_dict = goal

            # Determine the correct ConversionGoalFilter type based on kind
            kind = goal_dict.get("kind", NodeKind.EVENTS_NODE)
            # Clean up the goal_dict for each schema type
            cleaned_goal_dict = goal_dict.copy()

            if kind == NodeKind.EVENTS_NODE:
                # EventsNode doesn't need special field mapping
                converted_goal = ConversionGoalFilter1(**cleaned_goal_dict)
            elif kind == NodeKind.ACTIONS_NODE:
                # ActionsNode doesn't allow 'event' field - remove it
                if "event" in cleaned_goal_dict:
                    del cleaned_goal_dict["event"]
                converted_goal = ConversionGoalFilter2(**cleaned_goal_dict)
            elif kind == NodeKind.DATA_WAREHOUSE_NODE:
                # DataWarehouseNode doesn't allow 'event' field - remove it
                if "event" in cleaned_goal_dict:
                    del cleaned_goal_dict["event"]

                # ConversionGoalFilter3 expects both id_field and distinct_id_field
                if "distinct_id_field" in cleaned_goal_dict and "id_field" not in cleaned_goal_dict:
                    cleaned_goal_dict["id_field"] = cleaned_goal_dict["distinct_id_field"]
                    # Keep distinct_id_field as it's also required

                converted_goal = ConversionGoalFilter3(**cleaned_goal_dict)
            else:
                # Default to EventsNode
                converted_goal = ConversionGoalFilter1(**cleaned_goal_dict)

            converted_goals.append(converted_goal)

        except Exception as e:
            logger.exception(
                "Error converting team conversion goal", error=str(e), goal=str(goal), extra={"team_id": team_pk}
            )
            continue

    return converted_goals


def map_url_to_provider(url_pattern: str) -> str:
    """
    Mirror of frontend mapUrlToProvider function from DataWarehouseSourceIcon.tsx
    Maps URL patterns to platform providers for self-managed sources.

    Args:
        url_pattern: The URL pattern from a data warehouse table

    Returns:
        Platform identifier (aws, google-cloud, azure, cloudflare-r2) or 'BlushingHog' for unknown
    """
    if not url_pattern:
        return "BlushingHog"

    if "amazonaws.com" in url_pattern:
        return "aws"
    elif url_pattern.startswith("https://storage.googleapis.com"):
        return "google-cloud"
    elif ".blob." in url_pattern:
        return "azure"
    elif ".r2.cloudflarestorage.com" in url_pattern:
        return "cloudflare-r2"

    return "BlushingHog"


def sanitize_conversion_goal_name(name: str) -> str:
    """Sanitize conversion goal name to be a valid SQL identifier"""
    return "".join(c if c.isalnum() else "_" for c in name)
