from typing import Any

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def _references_cohort(value: Any, cohort_id: int) -> bool:
    # Cohort filters also nest inside event and action entries, so the walk covers the whole filter tree.
    if isinstance(value, list):
        return any(_references_cohort(item, cohort_id) for item in value)
    if not isinstance(value, dict):
        return False
    if value.get("type") == "cohort" and str(value.get("value")) == str(cohort_id):
        return True
    return any(_references_cohort(item, cohort_id) for item in value.values())


def _action_uses_realtime_cohort(action: Any, cohort_id: int) -> bool:
    if not isinstance(action, dict):
        return False
    config = action.get("config") or {}
    if action.get("type") == "trigger":
        return config.get("type") == "cohort" and config.get("cohort_id") == cohort_id
    if action.get("type") == "conditional_branch":
        return any(
            _references_cohort((condition or {}).get("filters"), cohort_id)
            for condition in config.get("conditions") or []
            if isinstance(condition, dict)
        )
    return False


def get_active_hog_flows_using_realtime_cohort(team_id: int, cohort_id: int) -> list[HogFlow]:
    """Active workflows that read the cohort's realtime membership: cohort triggers and conditional branches."""
    return [
        flow
        for flow in HogFlow.objects.filter(team_id=team_id, status=HogFlow.State.ACTIVE)
        if any(_action_uses_realtime_cohort(action, cohort_id) for action in (flow.actions or []))
    ]
