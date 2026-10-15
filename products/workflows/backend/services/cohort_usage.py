from collections.abc import Collection, Iterator
from typing import Any

from products.cdp.backend.presentation.hog_functions import filter_cohort_ids
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def _action_uses_realtime_cohort(action: Any, cohort_ids: set[int]) -> bool:
    if not isinstance(action, dict):
        return False
    config = action.get("config") or {}
    if action.get("type") == "trigger":
        return config.get("type") == "cohort" and config.get("cohort_id") in cohort_ids
    if action.get("type") == "conditional_branch":
        return any(
            not cohort_ids.isdisjoint(filter_cohort_ids(condition.get("filters")))
            for condition in config.get("conditions") or []
            if isinstance(condition, dict)
        )
    return False


def get_active_hog_flows_using_realtime_cohort(project_id: int, cohort_ids: Collection[int]) -> Iterator[HogFlow]:
    """Active workflows in the project that read the realtime membership of any of these cohorts, as a
    cohort trigger or in a conditional branch."""
    # Cohorts are shared by every environment in a project, so a workflow in any of them can rely on one.
    # Only the fields the check reads, streamed: full rows carry encrypted inputs and the whole graph.
    ids = set(cohort_ids)
    flows = HogFlow.objects.filter(team__project_id=project_id, status=HogFlow.State.ACTIVE).only(
        "id", "name", "status", "team_id", "actions"
    )
    for flow in flows.iterator():
        if any(_action_uses_realtime_cohort(action, ids) for action in (flow.actions or [])):
            yield flow
