"""Resolve implementation PR URLs linked to signal reports."""

from typing import Literal, cast

from django.db.models import Q

import structlog

from posthog.dataclasses import frozen
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import SignalActorKind, SignalReport, SignalReportAssignment
from products.signals.backend.task_run_artefacts import (
    NON_PR_BEARING_TASK_RUN_TYPES,
    SIGNALS_PRODUCT,
    TASK_RUN_TYPE_IMPLEMENTATION,
)
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

# A report in one of these statuses is finished with its pull request. Anything else still holds
# it open — a status this list doesn't know about keeps the PR, which is the safe direction.
_FINISHED_REPORT_STATUSES = frozenset(
    {SignalReport.Status.RESOLVED, SignalReport.Status.SUPPRESSED, SignalReport.Status.DELETED}
)


@frozen
class ImplementationPr:
    """The implementation PR surfaced for a report and its latest known state."""

    url: str
    merged: bool
    state: str = SignalReportAssignment.PrState.UNKNOWN


def fetch_implementation_pr_state_for_reports(report_ids: list[str]) -> dict[str, ImplementationPr]:
    """Return assignment PRs first, falling back to existing task-backed PRs."""
    if not report_ids:
        return {}
    result = {
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

    missing_report_ids = [str(report_id) for report_id in report_ids if str(report_id) not in result]
    if not missing_report_ids:
        return result

    runs_by_report = SignalReport.associated_task_runs_for_reports(
        report_ids=missing_report_ids,
        product=SIGNALS_PRODUCT,
    )
    pairs = [
        (report_id, run.task_id)
        for report_id, runs in runs_by_report.items()
        for run in sorted(runs, key=lambda run: run.type != TASK_RUN_TYPE_IMPLEMENTATION)
        if run.type not in NON_PR_BEARING_TASK_RUN_TYPES
    ]
    task_ids = [task_id for _, task_id in pairs]
    pr_url_by_task = tasks_facade.get_latest_pr_url_by_task(task_ids)
    merged_task_ids = tasks_facade.get_merged_pr_task_ids(task_ids)
    for report_id, task_id in pairs:
        pr_url = pr_url_by_task.get(task_id)
        if pr_url and report_id not in result:
            merged = task_id in merged_task_ids
            result[report_id] = ImplementationPr(
                url=pr_url,
                merged=merged,
                state=SignalReportAssignment.PrState.MERGED if merged else SignalReportAssignment.PrState.UNKNOWN,
            )
    return result


def pr_bearing_task_run_filter() -> Q:
    return Q(state__ai_stage__isnull=True) | (
        ~Q(state__ai_stage__in=sorted(NON_PR_BEARING_TASK_RUN_TYPES)) & ~Q(state__ai_stage__startswith="scout:")
    )


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
        assignment = SignalReportAssignment.all_teams.filter(
            report_id=report_id,
            report__team_id=team_id,
        ).first()
        if assignment is None or not assignment.pr_url:
            return False
        if assignment.actor_kind not in {SignalActorKind.TASK, SignalActorKind.SYSTEM}:
            logger.info(
                "close_implementation_pr_untrusted_actor",
                report_id=str(report_id),
                actor_kind=assignment.actor_kind,
            )
            return False
        pr_url = assignment.pr_url

        parsed = GitHubIntegrationBase.parse_pull_request_url(pr_url)
        if parsed is None:
            logger.warning("close_implementation_pr_unparseable_url", report_id=str(report_id), pr_url=pr_url)
            return False

        # Nothing serializes this call with a re-claim that swaps the pull request or with a merge
        # webhook, and both write the same row. Scope every write back to the pull request this call
        # read, so a result that arrives late lands on nothing instead of on its replacement.
        assignment_for_pr = SignalReportAssignment.all_teams.filter(
            report_id=report_id,
            report__team_id=team_id,
            repository=parsed.repository.lower(),
            pr_number=parsed.number,
        )

        # One pull request can back several reports. Closing it for one dismissal would close the
        # work the others still depend on, and the close webhook would then suppress them too, so
        # only the last report still using it closes it.
        still_used_elsewhere = (
            SignalReportAssignment.all_teams.filter(
                report__team_id=team_id,
                repository=parsed.repository.lower(),
                pr_number=parsed.number,
            )
            .exclude(report_id=report_id)
            .exclude(report__status__in=_FINISHED_REPORT_STATUSES)
            .exists()
        )
        if still_used_elsewhere:
            logger.info(
                "close_implementation_pr_still_used_by_another_report",
                report_id=str(report_id),
                pr_url=pr_url,
            )
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
            assignment_for_pr.update(
                pr_state=SignalReportAssignment.PrState.MERGED,
                pr_merged=True,
            )
        elif pr_status.get("state") == "closed":
            assignment_for_pr.update(
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
        # Closing a merged pull request is a no-op that still reports success, so a merge that landed
        # during the round trip must keep its state. A merge is terminal: no later webhook would
        # correct a downgrade here.
        assignment_for_pr.exclude(pr_state=SignalReportAssignment.PrState.MERGED).update(
            pr_state=SignalReportAssignment.PrState.CLOSED,
            pr_merged=False,
        )
        return True
    except Exception:
        logger.exception("close_implementation_pr_unexpected_error", report_id=str(report_id))
        return False
