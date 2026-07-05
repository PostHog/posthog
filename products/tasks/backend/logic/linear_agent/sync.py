"""Status sync from PostHog Code task runs back to Linear issues.

``dispatch_linear_update_for_run`` is called from the run-update side-effect hooks in
``facade/api.py`` (next to the Slack equivalent) and must never raise or add latency
there — it does one cheap existence check and defers the Linear API work to Celery.
"""

from typing import Literal

from django.conf import settings
from django.db import transaction

import structlog

from products.tasks.backend.logic.linear_agent.client import LinearAgentClient
from products.tasks.backend.models import LinearIssueTaskMapping, TaskRun

logger = structlog.get_logger(__name__)

LinearUpdateKind = Literal["pr_opened", "failed"]


def dispatch_linear_update_for_run(run: TaskRun, *, kind: LinearUpdateKind, error_message: str | None = None) -> None:
    """Queue a Linear comment for a run event when the run's task originated in Linear.

    The callers run in both DRF and Temporal-activity contexts, so the mapping lookup
    uses explicit ``.for_team(...)`` — there is no ambient team scope in workers.
    """
    if not LinearIssueTaskMapping.objects.for_team(run.team_id).filter(task_id=run.task_id).exists():
        return

    from products.tasks.backend.tasks import (  # noqa: PLC0415 — tasks.py imports this module; defer to break the cycle
        post_linear_update_for_run,
    )

    # on_commit so the Celery worker can't observe a run state older than what we're
    # reporting; immediate in autocommit mode.
    transaction.on_commit(
        lambda: post_linear_update_for_run.delay(run_id=str(run.id), kind=kind, error_message=error_message)
    )


def post_linear_update_for_run_impl(run_id: str, kind: str, error_message: str | None) -> None:
    """Celery task body: post the status comment (and agent activity) to Linear.

    Raises ``LinearAgentApiError`` so the task's autoretry can pick it up; every other
    failure mode returns quietly.
    """
    run = TaskRun.objects.filter(id=run_id).first()
    if run is None:
        return

    mapping = (
        LinearIssueTaskMapping.objects.for_team(run.team_id)
        .filter(task_id=run.task_id)
        .select_related("integration")
        .order_by("-created_at")
        .first()
    )
    if mapping is None:
        return

    body = _build_update_body(run, kind, error_message)
    if body is None:
        return

    client = LinearAgentClient(mapping.integration)
    client.create_comment(mapping.linear_issue_id, body)

    if mapping.linear_agent_session_id:
        activity_type = "error" if kind == "failed" else "response"
        try:
            client.create_agent_activity(mapping.linear_agent_session_id, body, activity_type=activity_type)
        except Exception:
            # The comment is the load-bearing update; session activity is best-effort
            # (sessions expire, and a retry would double-post the comment).
            logger.warning(
                "linear_agent_session_update_failed",
                run_id=run_id,
                agent_session_id=mapping.linear_agent_session_id,
            )


def _build_update_body(run: TaskRun, kind: str, error_message: str | None) -> str | None:
    if kind == "pr_opened":
        pr_url = (run.output or {}).get("pr_url") if isinstance(run.output, dict) else None
        if not pr_url:
            return None
        return f"PostHog Code opened a pull request: {pr_url}"

    if kind == "failed":
        task_url = f"{settings.SITE_URL}/project/{run.team_id}/tasks/{run.task_id}"
        reason = error_message or run.error_message or "unknown error"
        return f"PostHog Code run failed: {reason}\nDetails: {task_url}"

    logger.warning("linear_agent_unknown_update_kind", run_id=str(run.id), kind=kind)
    return None
