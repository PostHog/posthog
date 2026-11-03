"""Facade for issue summaries.

A module of its own, like ``queries.py``, so the HogQL and LLM client imports stay out of ``facade/api.py``.
"""

from uuid import UUID

from posthog.exceptions_capture import capture_exception
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
    """Turning the flag off also hides stored summaries. `read_issue_summary` checks the flag in the logic layer."""
    if summary is None or not issue_summaries.issue_summaries_enabled(team_id):
        return None
    return _to_summary(summary)


def get_issue_summary(team_id: int, issue_id: UUID | str, *, user: User) -> contracts.ErrorTrackingIssueSummary | None:
    """The stored summary, whatever its age, when `user` may read it. Never generates."""
    if not issue_summaries.summary_sources_readable(team_id, user):
        return None
    return _shown(team_id, issue_summaries.get_issue_summary(team_id, issue_id))


def read_issue_summary(team_id: int, issue_id: UUID | str, *, user: User, start: bool) -> contracts.IssueSummaryRead:
    """The stored summary and its status, at once. Never waits for generation, and never raises.

    `start` queues generation in the background when a summary is due.
    """
    try:
        state = issue_summaries.read_issue_summary(team_id, issue_id, user, start=start)
    except Exception as error:
        capture_exception(error, {"team_id": team_id, "issue_id": str(issue_id)})
        return contracts.IssueSummaryRead(
            status=contracts.IssueSummaryStatus.UNAVAILABLE,
            summary=None,
            reason=contracts.IssueSummaryUnavailableReason.ERROR,
            hint=None,
        )
    return contracts.IssueSummaryRead(
        status=state.status,
        summary=_to_summary(state.summary) if state.summary is not None else None,
        reason=state.reason,
        hint=state.hint,
    )
