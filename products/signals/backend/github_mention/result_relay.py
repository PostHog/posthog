"""Post the terminal result of a mention-triggered run back to its GitHub PR.

The GitHub analogue of the Slack completion relay: when a GITHUB_MENTION run reaches a terminal
state, the tasks completion path enqueues this task, which loads the run's PR mapping and posts one
closing comment. The message is scoped to the outcome only — never project or customer data — because
PR comments can be world-readable.
"""

from typing import Any, cast

import structlog
from celery import shared_task

from posthog.models.integration import GitHubIntegration
from posthog.scoping_audit import skip_team_scope_audit

from products.signals.backend.models import GitHubMentionTaskMapping

logger = structlog.get_logger(__name__)

_COMPLETED = "completed"
_FAILED = "failed"
_CANCELLED = "cancelled"


def _build_result_comment(status: str) -> str:
    if status == _COMPLETED:
        return "Done — I've addressed the feedback and pushed the changes to this PR."
    if status == _FAILED:
        return "I ran into an error while addressing the feedback and couldn't finish. Mention me again to retry."
    if status == _CANCELLED:
        return "The run to address this feedback was cancelled."
    return ""


@shared_task(ignore_result=True)
@skip_team_scope_audit
def relay_github_mention_result(*, run_id: str, status: str) -> None:
    body = _build_result_comment(status)
    if not body:
        return

    # Django coerces the str pk for the UUID FK lookup at runtime; django-stubs types it strictly.
    mapping = GitHubMentionTaskMapping.all_teams.filter(task_run_id=run_id).first()  # type: ignore[misc]
    if mapping is None:
        return

    github = GitHubIntegration.first_for_team_repository(mapping.team_id, mapping.repository)
    if github is None:
        logger.warning("github_mention_relay_no_integration", run_id=run_id, repository=mapping.repository)
        return

    outcome = github.comment_on_pull_request(mapping.repository, mapping.pr_number, body)
    if not outcome.get("success"):
        logger.warning("github_mention_relay_comment_failed", run_id=run_id, error=outcome.get("error"))


def enqueue_mention_result_relay(run_id: str, status: str) -> None:
    """Entry point the tasks completion path calls (via lazy import) on a terminal GITHUB_MENTION run."""
    cast(Any, relay_github_mention_result).delay(run_id=run_id, status=status)
