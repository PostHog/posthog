from rest_framework.request import Request

from posthog.models import Team

from products.signals.backend.facade.metric_access import may_read_metric_context
from products.tasks.backend.access import (
    DesktopAccessDecision,
    DesktopAccessResolutionError,
    get_desktop_access_decision,
    has_loops_access,
)
from products.tasks.backend.facade.contracts import DesktopAccessReason
from products.tasks.backend.logic.services.code_usage_gate import (
    code_access_required_response,
    compute_quota_limit_response,
    usage_limit_response,
)
from products.tasks.backend.models import TaskRun


def may_read_task_run_context(*, request: Request, team: Team, task_id: str, run_id: str | None) -> bool:
    runs = TaskRun.objects.filter(team_id=team.id, task_id=task_id)
    if run_id is not None:
        runs = runs.filter(id=run_id)
    if run_id is None:
        runs = runs.filter(state__has_key="analytics_query_context")
    return all(
        may_read_metric_context(request=request, team=team, queries=ancestor.state["analytics_query_context"])
        for run in runs
        for ancestor in (run.get_resume_chain() if (run.state or {}).get("resume_from_run_id") else [run])
        if "analytics_query_context" in (ancestor.state or {})
    )


__all__ = [
    "DesktopAccessDecision",
    "DesktopAccessReason",
    "DesktopAccessResolutionError",
    "code_access_required_response",
    "compute_quota_limit_response",
    "get_desktop_access_decision",
    "has_loops_access",
    "may_read_task_run_context",
    "usage_limit_response",
]
