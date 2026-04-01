"""Utility functions for working with experiment metrics."""

import copy
import logging
from typing import Any

from posthog.models.action.action import Action
from posthog.models.team.team import Team

logger = logging.getLogger(__name__)


def refresh_action_names_in_metric(query: dict[str, Any] | None, team: Team) -> dict[str, Any] | None:
    """
    Update ActionsNode names in a metric query to reflect current action names.

    This ensures that if an action is renamed, metrics display the latest name
    instead of the stale name that was stored when the metric was created.

    This function is defensive:
    - If an action is deleted, the old name is preserved
    - If there's an error fetching actions, the original query is returned unchanged
    - The original query is never mutated

    Args:
        query: The metric query dictionary (ExperimentMetric)
        team: The team to fetch actions for

    Returns:
        Updated query dict with refreshed action names, or original query if errors occur
    """
    if not query or query.get("kind") != "ExperimentMetric":
        return query

    try:
        # Create a copy to avoid mutating the original
        query = copy.deepcopy(query)

        # Collect all action IDs that need to be fetched
        action_ids: set[int] = set()
        _collect_action_ids(query, action_ids)

        if not action_ids:
            return query

        # Fetch all actions in a single query
        # Only include actions that still exist (not deleted)
        actions_by_id = {
            action.id: action.name for action in Action.objects.filter(id__in=action_ids, team=team, deleted=False)
        }

        # Update action names throughout the query
        # If an action was deleted, its ID won't be in actions_by_id and the old name will be preserved
        _update_action_names(query, actions_by_id)

        return query
    except Exception as e:
        # Be defensive - if anything goes wrong, return the original query unchanged
        logger.warning(
            "Error refreshing action names in metric query: %s",
            e,
            exc_info=True,
            extra={"team_id": team.id, "query_kind": query.get("kind") if query else None},
        )
        return query


def _collect_action_ids(obj: Any, action_ids: set[int]) -> None:
    """Recursively collect all action IDs from ActionsNode objects in the query."""
    if isinstance(obj, dict):
        if obj.get("kind") == "ActionsNode" and "id" in obj:
            # Convert to int in case it's stored as a string
            try:
                action_ids.add(int(obj["id"]))
            except (ValueError, TypeError):
                logger.warning("Invalid action ID in ActionsNode: %s", obj["id"])
        for value in obj.values():
            _collect_action_ids(value, action_ids)
    elif isinstance(obj, list):
        for item in obj:
            _collect_action_ids(item, action_ids)


def _update_action_names(obj: Any, actions_by_id: dict[int, str]) -> None:
    """Recursively update all ActionsNode name fields with current action names."""
    if isinstance(obj, dict):
        if obj.get("kind") == "ActionsNode" and "id" in obj:
            # Convert to int in case it's stored as a string
            try:
                action_id = int(obj["id"])
            except (ValueError, TypeError):
                logger.warning("Invalid action ID in ActionsNode: %s", obj["id"])
                return

            if action_id in actions_by_id:
                obj["name"] = actions_by_id[action_id]
        for value in obj.values():
            _update_action_names(value, actions_by_id)
    elif isinstance(obj, list):
        for item in obj:
            _update_action_names(item, actions_by_id)
