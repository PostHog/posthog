"""Celery tasks for the tasks product (autodiscovered via INSTALLED_APPS)."""

from typing import Any

import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

from products.tasks.backend.linear_agent.client import LinearAgentApiError
from products.tasks.backend.linear_agent.service import handle_linear_agent_event
from products.tasks.backend.linear_agent.sync import post_linear_update_for_run_impl

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
@skip_team_scope_audit  # Integration/Task/TaskRun use default managers; the fail-closed mapping model is queried via .for_team()
def process_linear_agent_event(payload: dict[str, Any]) -> None:
    """Process an inbound Linear agent webhook event.

    Deliberately no automatic retries: a retry after a partial failure (task created,
    later step failed) would create a duplicate task for the same issue.
    """
    handle_linear_agent_event(payload)


@shared_task(ignore_result=True, autoretry_for=(LinearAgentApiError,), max_retries=3, retry_backoff=True)
@skip_team_scope_audit  # TaskRun uses the default manager; the fail-closed mapping model is queried via .for_team()
def post_linear_update_for_run(run_id: str, kind: str, error_message: str | None = None) -> None:
    """Post a status update (PR opened / run failed) back to the originating Linear issue."""
    post_linear_update_for_run_impl(run_id=run_id, kind=kind, error_message=error_message)
