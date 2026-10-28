from collections.abc import Callable
from uuid import UUID

from products.signals.backend.facade.metric_access import metric_context_reader as analytics_context_reader
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


def is_sandbox_run_request(
    *, team_id: int, task_id: str, run_id: str | None, token_id: UUID, include_resume_sources: bool = False
) -> bool:
    if run_id is None:
        return False
    try:
        parsed_task_id, parsed_run_id = UUID(task_id), UUID(run_id)
    except (ValueError, TypeError):
        return False
    bound_runs = TaskRun.objects.filter(
        team_id=team_id,
        task_id=parsed_task_id,
        state__sandbox_oauth_token_ids__contains=[str(token_id)],
    )
    if bound_runs.filter(id=parsed_run_id).exists():
        return True
    if include_resume_sources:
        bound_run = bound_runs.select_related("task").first()
        return bound_run is not None and any(run.id == parsed_run_id for run in bound_run.get_resume_chain())
    return False


def may_read_task_run_context(
    *, team_id: int, task_id: str, run_id: str | None, reader: Callable[[object], bool]
) -> bool:
    runs = TaskRun.objects.filter(team_id=team_id, task_id=task_id)
    if run_id is not None:
        try:
            parsed_run_id = UUID(run_id)
        except (ValueError, TypeError):
            return False
        runs = runs.filter(id=parsed_run_id)
    if run_id is None:
        runs = runs.filter(state__has_key="analytics_query_context")
    return all(
        reader(run.state["analytics_query_context"]) for run in runs if "analytics_query_context" in (run.state or {})
    )


__all__ = [
    "analytics_context_reader",
    "DesktopAccessDecision",
    "DesktopAccessReason",
    "DesktopAccessResolutionError",
    "code_access_required_response",
    "compute_quota_limit_response",
    "get_desktop_access_decision",
    "has_loops_access",
    "is_sandbox_run_request",
    "may_read_task_run_context",
    "usage_limit_response",
]
