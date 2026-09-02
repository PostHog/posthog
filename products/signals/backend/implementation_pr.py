"""Resolve implementation PR URLs linked to signal reports."""

from typing import Literal, cast

import structlog

from posthog.dataclasses import frozen
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import SignalReportAssignment

logger = structlog.get_logger(__name__)


@frozen
class ImplementationPr:
    """The implementation PR surfaced for a report and its latest known state."""

    url: str
    merged: bool
    state: str = SignalReportAssignment.PrState.UNKNOWN


def fetch_implementation_pr_state_for_reports(report_ids: list[str]) -> dict[str, ImplementationPr]:
    """Return the PR stored on each report assignment, when present."""
    if not report_ids:
        return {}
    return {
        str(assignment.report_id): ImplementationPr(
            url=assignment.pr_url,
            merged=assignment.pr_merged,
            state=assignment.pr_state or SignalReportAssignment.PrState.UNKNOWN,
        )
        for assignment in SignalReportAssignment.all_teams.filter(
            report_id__in=report_ids,
            pr_url__isnull=False,
        ).exclude(pr_url="")
        if assignment.pr_url is not None
    }


def fetch_implementation_pr_urls_for_reports(report_ids: list[str]) -> dict[str, str]:
    """PR URL stored on each report assignment, when available."""
    return {report_id: pr.url for report_id, pr in fetch_implementation_pr_state_for_reports(report_ids).items()}


PrCloseReason = Literal["suppressed", "snoozed", "resolved"]

# Left on the PR before it's closed, so anyone looking at the PR sees why it was closed and how to undo it.
_PR_CLOSE_COMMENT_TEMPLATE = (
    "🔕 Closing this PR because the linked PostHog report was {action}.\n\n"
    "If that wasn't intended, restore the report in PostHog and reopen this PR."
)
_PR_CLOSE_COMMENTS: dict[PrCloseReason, str] = {
    reason: _PR_CLOSE_COMMENT_TEMPLATE.format(action=reason)
    for reason in cast(tuple[PrCloseReason, ...], ("suppressed", "snoozed"))
}
# A resolved report never reopens, so the undo advice above does not apply to it.
_PR_CLOSE_COMMENTS["resolved"] = (
    "🔕 Closing this PR because the linked PostHog report was resolved without it.\n\n"
    "If that wasn't intended, reopen this PR."
)


def close_implementation_pr_for_report(
    team_id: int,
    report_id: str,
    *,
    reason: PrCloseReason = "suppressed",
) -> bool:
    """Best-effort: comment on and close the GitHub PR attached to this report.

    Called when a report is suppressed, snoozed, or resolved without its PR — the open PR shouldn't linger. Only acts on a PR
    that is still open: an already-closed or merged PR is left untouched (no comment, no close), so
    we never leave a confusing "closing this PR" note on a PR that shipped months ago. Leaves an
    explanatory comment, then closes the PR. Returns True when the PR was closed, False when there
    was nothing to close or the close couldn't be completed. Never raises: the state transition
    must succeed regardless.
    """
    try:
        pr_url = (
            SignalReportAssignment.all_teams.filter(report_id=report_id, report__team_id=team_id)
            .values_list("pr_url", flat=True)
            .first()
        )
        if not pr_url:
            return False

        parsed = GitHubIntegrationBase.parse_pull_request_url(pr_url)
        if parsed is None:
            logger.warning("close_implementation_pr_unparseable_url", report_id=str(report_id), pr_url=pr_url)
            return False

        github = GitHubIntegration.first_for_team_repository(team_id, parsed.repository)
        if github is None:
            logger.info(
                "close_implementation_pr_no_integration", report_id=str(report_id), repository=parsed.repository
            )
            return False

        # Only comment on and close a PR that's still open. A merged PR reports state "closed" with
        # merged=True, and an already-closed PR reports state "closed" — in either case there's
        # nothing to close, and leaving a comment would just be noise. If the state can't be
        # confirmed, skip rather than risk commenting on a PR that already shipped.
        pr_status = github.get_pull_request(parsed.repository, parsed.number)
        if not pr_status.get("success"):
            logger.warning(
                "close_implementation_pr_status_fetch_failed",
                report_id=str(report_id),
                pr_url=pr_url,
                error=pr_status.get("error"),
                status_code=pr_status.get("status_code"),
            )
            return False
        if pr_status.get("merged"):
            SignalReportAssignment.all_teams.filter(report_id=report_id, report__team_id=team_id).update(
                pr_state=SignalReportAssignment.PrState.MERGED,
                pr_merged=True,
            )
        elif pr_status.get("state") == "closed":
            SignalReportAssignment.all_teams.filter(report_id=report_id, report__team_id=team_id).update(
                pr_state=SignalReportAssignment.PrState.CLOSED,
                pr_merged=False,
            )
        if pr_status.get("state") != "open" or pr_status.get("merged"):
            logger.info(
                "close_implementation_pr_not_open",
                report_id=str(report_id),
                pr_url=pr_url,
                state=pr_status.get("state"),
                merged=pr_status.get("merged"),
            )
            return False

        # Explain first, close second. A failed comment should not stop the close.
        comment_outcome = github.comment_on_pull_request(parsed.repository, parsed.number, _PR_CLOSE_COMMENTS[reason])
        if not comment_outcome.get("success"):
            logger.warning(
                "close_implementation_pr_comment_failed",
                report_id=str(report_id),
                pr_url=pr_url,
                error=comment_outcome.get("error"),
                status_code=comment_outcome.get("status_code"),
            )

        outcome = github.close_pull_request(parsed.repository, parsed.number)
        if not outcome.get("success"):
            logger.warning(
                "close_implementation_pr_failed",
                report_id=str(report_id),
                pr_url=pr_url,
                error=outcome.get("error"),
                status_code=outcome.get("status_code"),
            )
            return False
        SignalReportAssignment.all_teams.filter(report_id=report_id, report__team_id=team_id).update(
            pr_state=SignalReportAssignment.PrState.CLOSED,
            pr_merged=False,
        )
        return True
    except Exception:
        logger.exception("close_implementation_pr_unexpected_error", report_id=str(report_id))
        return False
