# Marketing Analytics Utility Functions

from typing import Any

import structlog
from pydantic import BaseModel

from posthog.schema import ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3, NodeKind

logger = structlog.get_logger(__name__)


def _filter_to_model_fields(goal_dict: dict[str, Any], model: type[BaseModel]) -> dict[str, Any]:
    """Keep only keys the target pydantic model declares, so extra fields (e.g. data-warehouse-only
    fields on a saved goal) don't trip the model's ``extra="forbid"`` validation."""
    allowed = model.model_fields.keys()
    return {key: value for key, value in goal_dict.items() if key in allowed}


def convert_team_conversion_goals_to_objects(
    team_conversion_goals, team_pk: int
) -> list[ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3]:
    """Convert team conversion goals from dict format to ConversionGoalFilter objects"""

    logger = structlog.get_logger(__name__)
    converted_goals: list[ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3] = []

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

            converted_goal: ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3
            if kind == NodeKind.EVENTS_NODE:
                # EventsNode doesn't need special field mapping
                converted_goal = ConversionGoalFilter1(
                    **_filter_to_model_fields(cleaned_goal_dict, ConversionGoalFilter1)
                )
            elif kind == NodeKind.ACTIONS_NODE:
                converted_goal = ConversionGoalFilter2(
                    **_filter_to_model_fields(cleaned_goal_dict, ConversionGoalFilter2)
                )
            elif kind == NodeKind.DATA_WAREHOUSE_NODE:
                # ConversionGoalFilter3 expects both id_field and distinct_id_field
                if "distinct_id_field" in cleaned_goal_dict and "id_field" not in cleaned_goal_dict:
                    cleaned_goal_dict["id_field"] = cleaned_goal_dict["distinct_id_field"]
                    # Keep distinct_id_field as it's also required

                converted_goal = ConversionGoalFilter3(
                    **_filter_to_model_fields(cleaned_goal_dict, ConversionGoalFilter3)
                )
            else:
                # Default to EventsNode
                converted_goal = ConversionGoalFilter1(
                    **_filter_to_model_fields(cleaned_goal_dict, ConversionGoalFilter1)
                )

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
