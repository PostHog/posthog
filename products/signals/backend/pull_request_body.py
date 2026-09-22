"""Backend edits to a self-driving pull request's description.

The agent writes the description, and the backend then adds sections it must not paraphrase, such
as the tracker issue reference and the Origin section. Every such edit reads the current body and
writes it back under the body's etag, so an edit never overwrites a change the agent made in between.
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
    # GitHub refused, the repository access check failed, or the body changed after the read.
    # A retry can succeed.
    FAILED = "failed"


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

    pull_request = github.get_pull_request(parsed.repository, parsed.number)
    if not pull_request.get("success"):
        logger.warning(
            f"{log_event}_pr_fetch_failed", report_id=report_id, pr_url=pr_url, error=pull_request.get("error")
        )
        return BodyEditOutcome.FAILED

    body = pull_request.get("body") or ""
    updated = edit(body, parsed.repository)
    if updated is None:
        return BodyEditOutcome.SKIPPED
    if updated == body:
        return BodyEditOutcome.WRITTEN

    outcome = github.update_pull_request_body(
        parsed.repository, parsed.number, updated, expected_etag=pull_request.get("etag")
    )
    if not outcome.get("success"):
        logger.warning(f"{log_event}_pr_update_failed", report_id=report_id, pr_url=pr_url, error=outcome.get("error"))
        return BodyEditOutcome.FAILED
    return BodyEditOutcome.WRITTEN
