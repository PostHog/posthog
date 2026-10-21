"""Facade for issue summaries.

A module of its own, like ``queries.py``, so the HogQL and LLM client imports stay out of ``facade/api.py``.
"""

import time
from datetime import datetime
from uuid import UUID

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic import issue_summaries
from products.error_tracking.backend.models import ErrorTrackingIssueSummary
from products.error_tracking.backend.tasks.tasks import generate_error_tracking_issue_summary

WAIT_POLL_INTERVAL_SECONDS = 0.25


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
    """Queue generation in the background when a summary may be due. Returns whether it queued a task.

    False means nothing will change soon, so the caller should not wait.
    """
    stored = issue_summaries.get_issue_summary(team_id, issue_id)
    if issue_summaries.generation_blocked(team_id, stored) is not None:
        return False
    generate_error_tracking_issue_summary.delay(team_id, str(issue_id))
    return True


def wait_for_issue_summary(
    team_id: int, issue_id: UUID | str, *, checked_after: datetime | None, timeout_seconds: float
) -> contracts.ErrorTrackingIssueSummary | None:
    """Poll for a summary generated or confirmed unchanged after `checked_after`, or any summary when it is None.

    Pass the time taken just before `start_issue_summary_generation`. Returns None at the timeout.
    The background task keeps running.
    """
    deadline = time.monotonic() + timeout_seconds
    while True:
        summary = issue_summaries.get_issue_summary(team_id, issue_id)
        if summary is not None and (checked_after is None or summary.checked_at > checked_after):
            return _to_summary(summary)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(WAIT_POLL_INTERVAL_SECONDS, remaining))
