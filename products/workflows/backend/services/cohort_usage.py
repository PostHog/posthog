from collections.abc import Iterator
from typing import Any

from products.cdp.backend.presentation.hog_functions import filter_cohort_ids
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def _action_uses_realtime_cohort(action: Any, cohort_id: int) -> bool:
    if not isinstance(action, dict):
        return False
    config = action.get("config") or {}
    if action.get("type") == "trigger":
        return config.get("type") == "cohort" and config.get("cohort_id") == cohort_id
    if action.get("type") == "conditional_branch":
        return any(
            cohort_id in filter_cohort_ids(condition.get("filters"))
            for condition in config.get("conditions") or []
            if isinstance(condition, dict)
        )
    return False


def get_active_hog_flows_using_realtime_cohort(team_id: int, cohort_id: int) -> Iterator[HogFlow]:
    """Active workflows that read the cohort's realtime membership: cohort triggers and conditional branches."""
    # Only the fields the check reads, streamed: full rows carry encrypted inputs and the whole graph.
    flows = HogFlow.objects.filter(team_id=team_id, status=HogFlow.State.ACTIVE).only("id", "name", "status", "actions")
    for flow in flows.iterator():
        if any(_action_uses_realtime_cohort(action, cohort_id) for action in (flow.actions or [])):
            yield flow
