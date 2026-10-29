"""Facade for issue summaries.

A module of its own, like ``queries.py``, so the HogQL and LLM client imports stay out of ``facade/api.py``.
"""

from datetime import datetime
from uuid import UUID

from posthog.models import User

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic import issue_summaries
from products.error_tracking.backend.models import ErrorTrackingIssueSummary


def _to_summary(summary: ErrorTrackingIssueSummary) -> contracts.ErrorTrackingIssueSummary:
    content = summary.content
    category = content.get("category")
    return contracts.ErrorTrackingIssueSummary(
        issue_id=summary.issue_id,
        what_happened=content["what_happened"],
        likely_cause=content["likely_cause"],
        who_is_affected=content["who_is_affected"],
        suggested_next_step=content["suggested_next_step"],
        category=contracts.IssueSummaryCategory(category)
        if category in contracts.IssueSummaryCategory.values
        else None,
        model=summary.model,
        generated_at=summary.generated_at,
        checked_at=summary.checked_at,
    )


def _shown(team_id: int, summary: ErrorTrackingIssueSummary | None) -> contracts.ErrorTrackingIssueSummary | None:
    """Every read returns through here, so turning the flag off also hides stored summaries."""
    if summary is None or not issue_summaries.issue_summaries_enabled(team_id):
        return None
    return _to_summary(summary)


def get_issue_summary(team_id: int, issue_id: UUID | str, *, user: User) -> contracts.ErrorTrackingIssueSummary | None:
    """The stored summary, whatever its age, when `user` may read it. Never generates."""
    if not issue_summaries.summary_sources_readable(team_id, user):
        return None
    return _shown(team_id, issue_summaries.get_issue_summary(team_id, issue_id))


def get_or_generate_issue_summary(
    team_id: int, issue_id: UUID | str, *, user: User
) -> contracts.ErrorTrackingIssueSummary | None:
    """Generate in the calling thread when a summary is due, else return the stored one. Blocks on the model."""
    if not issue_summaries.summary_sources_readable(team_id, user):
        return None
    return _shown(team_id, issue_summaries.get_or_generate_issue_summary(team_id, issue_id).summary)


def start_issue_summary_generation(team_id: int, issue_id: UUID | str, *, user: User) -> bool:
    """Queue generation in the background when a summary may be due. False means the caller should not wait.

    Also False when `user` may not read the summary, so that caller does not wait for one it cannot see.
    """
    if not issue_summaries.summary_sources_readable(team_id, user):
        return False
    return issue_summaries.start_issue_summary_generation(team_id, issue_id)


def wait_for_issue_summary(
    team_id: int, issue_id: UUID | str, *, user: User, checked_after: datetime | None, timeout_seconds: float
) -> contracts.ErrorTrackingIssueSummary | None:
    """Poll for a summary generated or confirmed unchanged after `checked_after`. None at the timeout."""
    if not issue_summaries.summary_sources_readable(team_id, user):
        return None
    summary = issue_summaries.wait_for_issue_summary(
        team_id, issue_id, checked_after=checked_after, timeout_seconds=timeout_seconds
    )
    return _shown(team_id, summary)
