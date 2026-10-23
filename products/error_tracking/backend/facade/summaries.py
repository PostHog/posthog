"""Facade for issue summaries.

A module of its own, like ``queries.py``, so the HogQL and LLM client imports stay out of ``facade/api.py``.
"""

from datetime import datetime
from uuid import UUID

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
    )


def get_issue_summary(team_id: int, issue_id: UUID | str) -> contracts.ErrorTrackingIssueSummary | None:
    """The stored summary, whatever its age. Never generates."""
    summary = issue_summaries.get_issue_summary(team_id, issue_id)
    return _to_summary(summary) if summary is not None else None


def get_or_generate_issue_summary(team_id: int, issue_id: UUID | str) -> contracts.ErrorTrackingIssueSummary | None:
    """Generate in the calling thread when a summary is due, else return the stored one. Blocks on the model."""
    result = issue_summaries.get_or_generate_issue_summary(team_id, issue_id)
    return _to_summary(result.summary) if result.summary is not None else None


def start_issue_summary_generation(team_id: int, issue_id: UUID | str) -> bool:
    """Queue generation in the background when a summary may be due. False means the caller should not wait."""
    return issue_summaries.start_issue_summary_generation(team_id, issue_id)


def wait_for_issue_summary(
    team_id: int, issue_id: UUID | str, *, checked_after: datetime | None, timeout_seconds: float
) -> contracts.ErrorTrackingIssueSummary | None:
    """Poll for a summary generated or confirmed unchanged after `checked_after`. None at the timeout."""
    summary = issue_summaries.wait_for_issue_summary(
        team_id, issue_id, checked_after=checked_after, timeout_seconds=timeout_seconds
    )
    return _to_summary(summary) if summary is not None else None
