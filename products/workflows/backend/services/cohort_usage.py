from collections.abc import Collection, Iterator
from typing import Any

from django.db.models import TextField
from django.db.models.functions import Cast

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


def get_active_hog_flows_using_realtime_cohort(team_id: int, cohort_ids: Collection[int]) -> Iterator[HogFlow]:
    """Active workflows in the environment that read the realtime membership of any of these cohorts, as a
    cohort trigger or in a conditional branch."""
    # Only the fields the check reads, streamed: full rows carry encrypted inputs and the whole graph.
    ids = set(cohort_ids)
    # Postgres skips workflows whose actions never mention a cohort, so only those graphs reach Python.
    flows = (
        HogFlow.objects.filter(team_id=team_id, status=HogFlow.State.ACTIVE)
        .alias(actions_text=Cast("actions", output_field=TextField()))
        .filter(actions_text__contains="cohort")
        .only("id", "name", "status", "actions")
    )
    for flow in flows.iterator():
        if any(_action_uses_realtime_cohort(action, ids) for action in (flow.actions or [])):
            yield flow
