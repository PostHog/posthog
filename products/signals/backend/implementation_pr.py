"""Resolve implementation PR URLs linked to signal reports."""

from dataclasses import dataclass
from typing import Literal, cast

import structlog

from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.resolve_reviewers import (
    normalized_github_logins_from_suggested_reviewer_artefacts,
)
from products.signals.backend.task_run_artefacts import SIGNALS_PRODUCT, TASK_RUN_TYPE_IMPLEMENTATION
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ImplementationPr:
    """The one implementation PR surfaced for a report, and whether the webhook saw it merge."""

    url: str
    merged: bool


def fetch_implementation_pr_state_for_reports(report_ids: list[str]) -> dict[str, ImplementationPr]:
    """The implementation PR surfaced for each report, with its merge state, when one exists.

    The task↔report association comes from `SignalReport.associated_task_runs_for_reports` (the
    unified view of the `task_run` artefact log + legacy gate rows, batched over the whole page);
    the facade then resolves the latest PR-bearing run for each task, so multiple runs of a task
    collapse to the newest PR.

    A report can be associated with several implementation tasks (retries), but only one PR is
    surfaced — the first associated task that has one. The merge flag is read from *that* task, so
    the URL and its state always describe the same PR. Reading them independently would let a
    retry's merged PR vouch for a different PR's URL.
    """
    if not report_ids:
        return {}

    # (report_id, task_id) for each report's implementation task(s); signals owns this mapping.
    # Batched across the whole page so association costs two queries, not two per report (N+1).
    runs_by_report = SignalReport.associated_task_runs_for_reports(
        report_ids=[str(report_id) for report_id in report_ids],
        product=SIGNALS_PRODUCT,
        type=TASK_RUN_TYPE_IMPLEMENTATION,
    )
    pairs: list[tuple[str, str]] = [
        (report_id, run.task_id) for report_id, runs in runs_by_report.items() for run in runs
    ]
    if not pairs:
        return {}

    task_ids = [task_id for _, task_id in pairs]
    pr_url_by_task = tasks_facade.get_latest_pr_url_by_task(task_ids)
    merged_task_ids = tasks_facade.get_merged_pr_task_ids(task_ids)

    result: dict[str, ImplementationPr] = {}
    for report_id, task_id in pairs:
        pr_url = pr_url_by_task.get(task_id)
        if pr_url and report_id not in result:
            result[report_id] = ImplementationPr(url=pr_url, merged=task_id in merged_task_ids)
    return result


def fetch_implementation_pr_urls_for_reports(report_ids: list[str]) -> dict[str, str]:
    """PR URL from the latest implementation task run for each report, when available."""
    return {report_id: pr.url for report_id, pr in fetch_implementation_pr_state_for_reports(report_ids).items()}


PrCloseReason = Literal["suppressed", "snoozed"]

# Left on the PR before it's closed, so anyone looking at the PR sees why it was closed and how to undo it.
_PR_CLOSE_COMMENT_TEMPLATE = (
    "🔕 Closing this PR because the linked PostHog report was {action}.\n\n"
    "If that wasn't intended, restore the report in PostHog and reopen this PR."
)
_PR_CLOSE_COMMENTS: dict[PrCloseReason, str] = {
    reason: _PR_CLOSE_COMMENT_TEMPLATE.format(action=reason)
    for reason in cast(tuple[PrCloseReason, ...], ("suppressed", "snoozed"))
}


def close_implementation_pr_for_report(
    team_id: int,
    report_id: str,
    *,
    reason: PrCloseReason = "suppressed",
) -> bool:
    """Best-effort: comment on and close the GitHub PR opened for this report's implementation task.

    Called when a report is suppressed or snoozed — the open PR shouldn't linger. Only acts on a PR
    that is still open: an already-closed or merged PR is left untouched (no comment, no close), so
    we never leave a confusing "closing this PR" note on a PR that shipped months ago. Leaves an
    explanatory comment, then closes the PR. Returns True when the PR was closed, False when there
    was nothing to close or the close couldn't be completed. Never raises: the state transition
    must succeed regardless.
    """
    try:
        pr_url = fetch_implementation_pr_urls_for_reports([str(report_id)]).get(str(report_id))
        if not pr_url:
            return False

        parsed = GitHubIntegrationBase.parse_pull_request_url(pr_url)
        if parsed is None:
            logger.warning("close_implementation_pr_unparseable_url", report_id=str(report_id), pr_url=pr_url)
            return False
        owner, repo, pr_number = parsed
        repository = f"{owner}/{repo}"

        github = GitHubIntegration.first_for_team_repository(team_id, repository)
        if github is None:
            logger.info("close_implementation_pr_no_integration", report_id=str(report_id), repository=repository)
            return False

        # Only comment on and close a PR that's still open. A merged PR reports state "closed" with
        # merged=True, and an already-closed PR reports state "closed" — in either case there's
        # nothing to close, and leaving a comment would just be noise. If the state can't be
        # confirmed, skip rather than risk commenting on a PR that already shipped.
        pr_status = github.get_pull_request(repository, pr_number)
        if not pr_status.get("success"):
            logger.warning(
                "close_implementation_pr_status_fetch_failed",
                report_id=str(report_id),
                pr_url=pr_url,
                error=pr_status.get("error"),
                status_code=pr_status.get("status_code"),
            )
            return False
        if pr_status.get("state") != "open" or pr_status.get("merged"):
            logger.info(
                "close_implementation_pr_not_open",
                report_id=str(report_id),
                pr_url=pr_url,
                state=pr_status.get("state"),
                merged=pr_status.get("merged"),
            )
            return False

        # Explain first, close second — a failed comment shouldn't stop the close.
        comment_outcome = github.comment_on_pull_request(repository, pr_number, _PR_CLOSE_COMMENTS[reason])
        if not comment_outcome.get("success"):
            logger.warning(
                "close_implementation_pr_comment_failed",
                report_id=str(report_id),
                pr_url=pr_url,
                error=comment_outcome.get("error"),
                status_code=comment_outcome.get("status_code"),
            )

        outcome = github.close_pull_request(repository, pr_number)
        if not outcome.get("success"):
            logger.warning(
                "close_implementation_pr_failed",
                report_id=str(report_id),
                pr_url=pr_url,
                error=outcome.get("error"),
                status_code=outcome.get("status_code"),
            )
            return False
        return True
    except Exception:
        logger.exception("close_implementation_pr_unexpected_error", report_id=str(report_id))
        return False


def _report_reviewer_login_sets(team_id: int, report_id: str) -> tuple[frozenset[str], frozenset[str]]:
    """``(current reviewers, every login ever suggested for this report)``.

    Current is the latest `suggested_reviewers` artefact. The historical union is what lets us
    retract a review request we once set but the report has since dropped, without disturbing a
    reviewer a human added straight on GitHub — that login never appears in our artefacts.
    """
    artefacts = list(
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        ).order_by("-created_at")
    )
    if not artefacts:
        return frozenset(), frozenset()
    # `ever_managed` is lossy where a row was edited in place (`update_content` overwrites content),
    # so a login that only existed in a since-edited-away version isn't retracted — acceptable, since
    # the common reviewer-edit path appends a new row rather than editing, preserving history.
    desired = normalized_github_logins_from_suggested_reviewer_artefacts([artefacts[0]])
    ever_managed = desired | normalized_github_logins_from_suggested_reviewer_artefacts(artefacts[1:])
    return desired, ever_managed


def sync_reviewers_to_github_for_report(team_id: int, report_id: str) -> bool:
    """Best-effort: reconcile the report's reviewers with its open implementation PR's review requests.

    Run whenever a report's reviewers change and when its PR is first opened, so the GitHub PR's
    requested reviewers track the reviewers shown on the report — reports were surfacing reviewers
    that were never requested on the PR, so nobody got pinged.

    Reconciles both directions against the PR's current requests: it requests reviewers the report
    now names, and cancels pending requests for reviewers the report has dropped. Removal is scoped
    to logins we ourselves ever suggested, so a reviewer a human added on GitHub is left intact.
    Only logins we actually have (the `github_login` on each reviewer entry) are sent, and GitHub
    silently drops any it can't resolve to a collaborator — "to the extent we know the profile".
    Acts only on an open PR: a merged or closed PR is left alone. Idempotent, so re-running is a
    no-op. Returns True when a request was added or removed. Never raises: it hangs off a report
    write and must never fail it.
    """
    try:
        pr = fetch_implementation_pr_state_for_reports([str(report_id)]).get(str(report_id))
        if pr is None or pr.merged:
            return False

        desired, ever_managed = _report_reviewer_login_sets(team_id, str(report_id))
        if not ever_managed:  # the report has never named a reviewer — nothing to add or retract
            return False

        parsed = GitHubIntegrationBase.parse_pull_request_url(pr.url)
        if parsed is None:
            logger.warning("sync_reviewers_unparseable_url", report_id=str(report_id), pr_url=pr.url)
            return False
        owner, repo, pr_number = parsed
        repository = f"{owner}/{repo}"

        github = GitHubIntegration.first_for_team_repository(team_id, repository)
        if github is None:
            logger.info("sync_reviewers_no_integration", report_id=str(report_id), repository=repository)
            return False

        # The facade's merge flag comes from the webhook and can lag; confirm the PR is open before
        # touching review requests, so a PR closed without merging is left alone. The same call also
        # carries the PR's current pending reviewers, so no second GET is needed to diff against them.
        pr_status = github.get_pull_request(repository, pr_number)
        if not pr_status.get("success") or pr_status.get("state") != "open" or pr_status.get("merged"):
            return False

        # Case-insensitive diffs: our logins are already lowercased, and get_pull_request lowercases too.
        already_logins = set(pr_status.get("requested_reviewers") or [])
        missing = sorted(desired - already_logins)
        # Retract only reviewers we set that the report has since dropped, never a manual addition.
        stale = sorted((already_logins & ever_managed) - desired)
        if not missing and not stale:
            return True

        acted = False
        if missing:
            outcome = github.request_pull_request_reviewers(repository, pr_number, missing)
            if outcome.get("success"):
                acted = True
            logger.info(
                "sync_reviewers_requested",
                report_id=str(report_id),
                pr_url=pr.url,
                requested=outcome.get("requested"),
                rejected=outcome.get("rejected"),
                error=outcome.get("error"),
            )
        if stale:
            outcome = github.remove_pull_request_reviewers(repository, pr_number, stale)
            if outcome.get("success"):
                acted = True
            logger.info(
                "sync_reviewers_removed",
                report_id=str(report_id),
                pr_url=pr.url,
                removed=outcome.get("removed"),
                error=outcome.get("error"),
            )
        return acted
    except Exception:
        logger.exception("sync_reviewers_unexpected_error", report_id=str(report_id))
        return False
