"""Facade for issue summaries.

A module of its own, like ``queries.py``, so the HogQL and LLM client imports stay out of ``facade/api.py``.
"""

from uuid import UUID

from posthog.models import User

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic import issue_summaries
from products.error_tracking.backend.models import ErrorTrackingIssueSummary


def _to_summary(summary: ErrorTrackingIssueSummary) -> contracts.ErrorTrackingIssueSummary:
    content = summary.content
    return contracts.ErrorTrackingIssueSummary(
        issue_id=summary.issue_id,
        what_happened=content["what_happened"],
        likely_cause=content["likely_cause"],
        who_is_affected=content["who_is_affected"],
        suggested_next_step=content["suggested_next_step"],
        model=summary.model,
        generated_at=summary.generated_at,
        checked_at=summary.checked_at,
    )


def read_issue_summary(team_id: int, issue_id: UUID | str, *, user: User) -> contracts.IssueSummaryRead:
    """The stored summary, or the reason `user` sees none. Never starts generation.

    The output check runs again here because a row stored before the check existed stays, and nothing replaces it.
    """
    state = issue_summaries.read_issue_summary(team_id, issue_id, user)
    if state.summary is not None and issue_summaries.unsafe_summary_fields(state.summary.content):
        return contracts.IssueSummaryRead(status=contracts.IssueSummaryStatus.NOT_GENERATED, summary=None, reason=None)
    return contracts.IssueSummaryRead(
        status=state.status,
        summary=_to_summary(state.summary) if state.summary is not None else None,
        reason=state.reason,
    )
