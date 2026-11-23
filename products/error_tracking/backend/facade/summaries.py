"""Facade for issue summaries.

A module of its own, like ``queries.py``, so the HogQL and LLM client imports stay out of ``facade/api.py``.
"""

from typing import assert_never
from uuid import UUID

from posthog.models import User

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic import issue_summaries
from products.error_tracking.backend.logic.issue_summaries import IssueSummaryOutcome
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
    """The stored summary, or the reason `user` sees none. Never starts generation."""
    state = issue_summaries.read_issue_summary(team_id, issue_id, user)
    return contracts.IssueSummaryRead(
        status=state.status,
        summary=_to_summary(state.summary) if state.summary is not None else None,
        reason=state.reason,
    )


def summarize_issue(team_id: int, issue_id: UUID | str, *, user: User) -> contracts.IssueSummarize:
    """Generate the summary of an issue that has none, because `user` asked for it. Each generation uses AI credits."""
    result = issue_summaries.generate_issue_summary_on_demand(team_id, issue_id, user)
    if result.summary is not None:
        return contracts.IssueSummarize(
            outcome=contracts.IssueSummarizeOutcome.READY, summary=_to_summary(result.summary)
        )
    return contracts.IssueSummarize(outcome=_summarize_outcome(result.outcome), summary=None)


def _summarize_outcome(outcome: IssueSummaryOutcome) -> contracts.IssueSummarizeOutcome:
    match outcome:
        case IssueSummaryOutcome.DISABLED:
            return contracts.IssueSummarizeOutcome.DISABLED
        case IssueSummaryOutcome.RESTRICTED:
            return contracts.IssueSummarizeOutcome.RESTRICTED
        case IssueSummaryOutcome.SETTING_OFF:
            return contracts.IssueSummarizeOutcome.SETTING_OFF
        case IssueSummaryOutcome.AI_NOT_APPROVED:
            return contracts.IssueSummarizeOutcome.AI_NOT_APPROVED
        case IssueSummaryOutcome.OUT_OF_CREDITS:
            return contracts.IssueSummarizeOutcome.OUT_OF_CREDITS
        case IssueSummaryOutcome.RATE_LIMITED:
            return contracts.IssueSummarizeOutcome.RATE_LIMITED
        case IssueSummaryOutcome.IN_PROGRESS:
            return contracts.IssueSummarizeOutcome.IN_PROGRESS
        case IssueSummaryOutcome.ISSUE_MISSING:
            return contracts.IssueSummarizeOutcome.ISSUE_MISSING
        case IssueSummaryOutcome.NO_EXCEPTION:
            return contracts.IssueSummarizeOutcome.NO_EXCEPTION
        # GENERATED and FRESH always carry a summary, so they never reach this match.
        case (
            IssueSummaryOutcome.GENERATED
            | IssueSummaryOutcome.FRESH
            | IssueSummaryOutcome.INPUTS_ERROR
            | IssueSummaryOutcome.GATEWAY_UNCONFIGURED
            | IssueSummaryOutcome.MODEL_ERROR
            | IssueSummaryOutcome.INVALID_OUTPUT
            | IssueSummaryOutcome.UNEXPECTED_ERROR
        ):
            return contracts.IssueSummarizeOutcome.FAILED
        case _:
            assert_never(outcome)
