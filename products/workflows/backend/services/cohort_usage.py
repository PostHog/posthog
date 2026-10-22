from collections.abc import Collection, Iterator
from typing import Any

from django.db.models import Q, QuerySet, TextField
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


def _conversion_uses_realtime_cohort(conversion: Any, cohort_ids: set[int]) -> bool:
    if not isinstance(conversion, dict):
        return False
    return not cohort_ids.isdisjoint(filter_cohort_ids({"properties": conversion.get("filters") or []}))


def _active_hog_flows_mentioning_cohorts(team_id: int) -> QuerySet[HogFlow]:
    # Postgres skips workflows whose graph and goal never mention a cohort, so only those reach Python.
    return (
        HogFlow.objects.filter(team_id=team_id, status=HogFlow.State.ACTIVE)
        .alias(
            actions_text=Cast("actions", output_field=TextField()),
            conversion_text=Cast("conversion", output_field=TextField()),
        )
        .filter(Q(actions_text__contains="cohort") | Q(conversion_text__contains="cohort"))
    )


def team_has_active_hog_flows_mentioning_cohorts(team_id: int) -> bool:
    return _active_hog_flows_mentioning_cohorts(team_id).exists()


def get_active_hog_flows_using_realtime_cohort(team_id: int, cohort_ids: Collection[int]) -> Iterator[HogFlow]:
    """Active workflows in the environment that read the realtime membership of any of these cohorts, as a
    cohort trigger, in a conditional branch or in the conversion goal."""
    # Only the fields the check reads, streamed: full rows carry encrypted inputs and the whole graph.
    ids = set(cohort_ids)
    flows = _active_hog_flows_mentioning_cohorts(team_id).only("id", "name", "status", "actions", "conversion")
    for flow in flows.iterator():
        if _conversion_uses_realtime_cohort(flow.conversion, ids) or any(
            _action_uses_realtime_cohort(action, ids) for action in (flow.actions or [])
        ):
            yield flow
