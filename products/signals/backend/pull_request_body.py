"""Backend edits to a self-driving pull request's description.

The agent writes the description, and the backend then adds sections it must not paraphrase, such
as the tracker issue reference and the Origin section. GitHub has no conditional write for a pull
request body, so every edit reads the body again right before the write and backs off when it changed.
A change that lands between that second read and the write can still get lost.
"""

from collections.abc import Callable
from enum import StrEnum

import structlog

from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration

logger = structlog.get_logger(__name__)


class BodyEditOutcome(StrEnum):
    WRITTEN = "written"
    # Nothing to write, or the URL is not a GitHub pull request. A retry cannot change that.
    SKIPPED = "skipped"
    # GitHub refused, the repository access check failed, or the body changed during the edit.
    # A retry can succeed.
    FAILED = "failed"


def _read_body(
    github: GitHubIntegration, repository: str, number: int, *, report_id: str, pr_url: str, log_event: str
) -> str | None:
    pull_request = github.get_pull_request(repository, number)
    if not pull_request.get("success"):
        logger.warning(
            f"{log_event}_pr_fetch_failed", report_id=report_id, pr_url=pr_url, error=pull_request.get("error")
        )
        return None
    return pull_request.get("body") or ""


def edit_pull_request_body(
    *, team_id: int, report_id: str, pr_url: str, edit: Callable[[str, str], str | None], log_event: str
) -> BodyEditOutcome:
    """Apply `edit` to a pull request body and write the result back when it changed.

    `edit` receives the body and the `owner/repo` of the pull request. It returns the new body, or
    None when it has nothing to write. A body that `edit` returns unchanged counts as written.
    """
    parsed = GitHubIntegrationBase.parse_pull_request_url(pr_url)
    if parsed is None:
        return BodyEditOutcome.SKIPPED
    github = GitHubIntegration.first_for_team_repository(team_id, parsed.repository)
    if github is None:
        # The lookup also returns None when the access check hits a transient GitHub error.
        logger.info(f"{log_event}_no_integration", report_id=report_id, pr_url=pr_url)
        return BodyEditOutcome.FAILED

    body = _read_body(github, parsed.repository, parsed.number, report_id=report_id, pr_url=pr_url, log_event=log_event)
    if body is None:
        return BodyEditOutcome.FAILED
    updated = edit(body, parsed.repository)
    if updated is None:
        return BodyEditOutcome.SKIPPED
    if updated == body:
        return BodyEditOutcome.WRITTEN

    # `edit` can take seconds (the Origin section queries ClickHouse), and the agent can edit the body in that time.
    latest = _read_body(
        github, parsed.repository, parsed.number, report_id=report_id, pr_url=pr_url, log_event=log_event
    )
    if latest is None:
        return BodyEditOutcome.FAILED
    if latest != body:
        logger.info(f"{log_event}_pr_body_changed", report_id=report_id, pr_url=pr_url)
        return BodyEditOutcome.FAILED

    outcome = github.update_pull_request_body(parsed.repository, parsed.number, updated)
    if not outcome.get("success"):
        logger.warning(f"{log_event}_pr_update_failed", report_id=report_id, pr_url=pr_url, error=outcome.get("error"))
        return BodyEditOutcome.FAILED
    return BodyEditOutcome.WRITTEN
