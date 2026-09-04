"""Resolve implementation PR URLs linked to signal reports."""

from dataclasses import dataclass
from typing import Literal, cast

from django.db.models import Q

import structlog

from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import SignalReport
from products.signals.backend.task_run_artefacts import (
    NON_PR_BEARING_TASK_RUN_TYPES,
    SIGNALS_PRODUCT,
    TASK_RUN_TYPE_IMPLEMENTATION,
)
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

    Every code-shipping signals task associated with the report is a candidate, not just the `implementation`
    ones: a task started from the inbox's "Discuss" button runs the same agent against the same
    repo, so it can push a branch and open a PR too, and that PR is the report's PR as much as an
    auto-started one is. Implementation tasks are still consulted first, so a report that has both
    surfaces exactly what it surfaced before.

    Research, repo-selection, and scout runs are never candidates (`NON_PR_BEARING_TASK_RUN_TYPES`):
    they read other people's PRs while checking for in-flight work, and a PR URL recorded on one of
    them is a PR the agent saw, not one it opened. Surfacing it would label a stranger's PR as the
    report's, and `close_implementation_pr_for_report` would then close it on dismissal.

    A report can be associated with several tasks (retries, plus any discussion), but only one PR is
    surfaced — the first candidate that has one. The merge flag is read from *that* task, so the URL
    and its state always describe the same PR. Reading them independently would let a retry's merged
    PR vouch for a different PR's URL.

    Within each group the newest task leads, so a report whose fix was superseded surfaces the
    replacement rather than the PR it replaced.
    """
    if not report_ids:
        return {}

    # (report_id, task_id) for each report's signals task(s); signals owns this mapping.
    # Batched across the whole page so association costs two queries, not two per report (N+1).
    runs_by_report = SignalReport.associated_task_runs_for_reports(
        report_ids=[str(report_id) for report_id in report_ids],
        product=SIGNALS_PRODUCT,
    )
    pairs: list[tuple[str, str]] = [
        (report_id, run.task_id)
        for report_id, runs in runs_by_report.items()
        # Implementation tasks lead, and newest first within each group. `runs` arrives oldest-first,
        # so negating the index is what puts the newest first: superseding a report's fix adds a
        # second implementation task, and the replacement PR is the one to surface.
        for _, run in sorted(enumerate(runs), key=lambda pair: (pair[1].type != TASK_RUN_TYPE_IMPLEMENTATION, -pair[0]))
        if run.type not in NON_PR_BEARING_TASK_RUN_TYPES
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


def pr_bearing_task_run_filter() -> Q:
    """SQL counterpart of the `NON_PR_BEARING_TASK_RUN_TYPES` exclusion, as a `Q` on `tasks.TaskRun`.

    The run type lives in artefact JSON the SQL path deliberately doesn't cast, so this keys on the
    `state.ai_stage` stamp the pipeline writes at run creation, which carries the same names
    (`research`, `repo_selection`, `scout:<skill>`). Runs without a stamp pass, matching the Python
    path, where an unlabelled legacy association is a candidate.
    """
    return Q(state__ai_stage__isnull=True) | (
        ~Q(state__ai_stage__in=sorted(NON_PR_BEARING_TASK_RUN_TYPES)) & ~Q(state__ai_stage__startswith="scout:")
    )


def fetch_implementation_pr_urls_for_reports(report_ids: list[str]) -> dict[str, str]:
    """PR URL from the latest PR-bearing task run for each report, when available."""
    return {report_id: pr.url for report_id, pr in fetch_implementation_pr_state_for_reports(report_ids).items()}


PrCloseReason = Literal["suppressed", "snoozed", "resolved", "superseded"]

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
# Superseding says something different from the other two: the report is still open, and the work
# continues in another PR. The replacement's own description explains what changed, so this only has
# to get the reader there.
# It must not offer closing the replacement as the undo. The replacement is the report's newest
# implementation task, so `report_has_newer_implementation_task` is False for it and the
# `skip_superseded` guard does not spare it: closing it unmerged archives a report that is still
# being worked, and the report goes on surfacing that closed PR because `get_latest_pr_url_by_task`
# does not read PR state.
_SUPERSEDED_COMMENT = (
    "🔕 Closing this PR because more research changed what the fix should be. "
    "The report it came from is still open, and {replacement} replaces this PR.\n\n"
    "That PR's description says what changed. If this one was still the right fix, reopen it and "
    "say so on the replacement. Leave the replacement open. Closing it archives the report in "
    "PostHog, and the report still links to the replacement rather than to this PR."
)
_SUPERSEDED_COMMENT_NO_URL = (
    "🔕 Closing this PR because more research changed what the fix should be. "
    "The report it came from is still open, and a new PR replaces this one.\n\n"
    "If this PR was still the right fix, reopen it."
)


def _pr_close_comment(reason: PrCloseReason, replacement_pr_url: str | None) -> str:
    if reason != "superseded":
        return _PR_CLOSE_COMMENTS[reason]
    if replacement_pr_url:
        return _SUPERSEDED_COMMENT.format(replacement=replacement_pr_url)
    return _SUPERSEDED_COMMENT_NO_URL


def close_implementation_pr_for_report(
    team_id: int,
    report_id: str,
    *,
    reason: PrCloseReason = "suppressed",
    pr_url: str | None = None,
    replacement_pr_url: str | None = None,
) -> bool:
    """Best-effort: comment on and close the GitHub PR opened for this report's implementation task.

    Called when a report is suppressed, snoozed, or resolved without its PR — the open PR shouldn't linger. Only acts on a PR
    that is still open: an already-closed or merged PR is left untouched (no comment, no close), so
    we never leave a confusing "closing this PR" note on a PR that shipped months ago. Leaves an
    explanatory comment, then closes the PR. Returns True when the PR was closed, False when there
    was nothing to close or the close couldn't be completed. Never raises: the state transition
    must succeed regardless.
    """
    try:
        # `pr_url` is passed when the caller already knows which PR to close. Superseding does: the
        # report's surfaced PR is the replacement by then, so resolving it here would close the new
        # PR instead of the one it replaced.
        pr_url = pr_url or fetch_implementation_pr_urls_for_reports([str(report_id)]).get(str(report_id))
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
        comment_outcome = github.comment_on_pull_request(
            parsed.repository, parsed.number, _pr_close_comment(reason, replacement_pr_url)
        )
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
        return True
    except Exception:
        logger.exception("close_implementation_pr_unexpected_error", report_id=str(report_id))
        return False


def _implementation_task_ids_for_report(team_id: int, report_id: str) -> list[str]:
    """The report's implementation task ids, oldest first."""
    return [
        run.task_id
        for run in SignalReport.associated_task_runs(
            report_id=report_id, team_id=team_id, product=SIGNALS_PRODUCT, type=TASK_RUN_TYPE_IMPLEMENTATION
        )
    ]


def fetch_implementation_task_pr_url(team_id: int, report_id: str) -> str | None:
    """The newest PR opened by one of the report's own implementation tasks, when it has one.

    Narrower than `fetch_implementation_pr_urls_for_reports`, which also surfaces the PR of a task
    a person started from "Discuss". That is the right contract for display, but the wrong one for
    superseding: `close_superseded_implementation_prs` only ever closes implementation PRs, so a
    Discuss PR resolved here would promise a handover that can never happen — leaving the report
    with two open pull requests, the newer one claiming to have replaced the other.
    """
    task_ids = _implementation_task_ids_for_report(team_id, report_id)
    if not task_ids:
        return None
    pr_url_by_task = tasks_facade.get_latest_pr_url_by_task(task_ids)
    # Newest first, matching what the report surfaces: a replacement wins over what it replaced.
    for candidate_task_id in reversed(task_ids):
        pr_url = pr_url_by_task.get(candidate_task_id)
        if pr_url:
            return pr_url
    return None


def report_has_newer_implementation_task(team_id: int, report_id: str, task_id: str) -> bool:
    """Whether the report started another implementation after ``task_id``.

    This is what separates a superseded pull request from an abandoned one. A closed-unmerged PR
    normally archives its report, on the reading that somebody decided the work was not wanted. That
    reading is wrong when the report has since started a replacement: the fix moved, and archiving
    would drop a report that is actively being worked.
    """
    task_ids = _implementation_task_ids_for_report(team_id, report_id)
    if str(task_id) not in task_ids:
        return False
    return task_ids.index(str(task_id)) < len(task_ids) - 1


def close_superseded_implementation_prs(*, team_id: int, report_id: str, task_id: str, pr_url: str) -> int:
    """Close the pull requests of implementation tasks this report started before ``task_id``.

    Called when a replacement PR opens, rather than polled after the task is created: the report must
    never be left with no open PR at all, so the old one closes only once its replacement exists.
    Returns how many were closed. Never raises — a failed handover leaves both PRs open, which a
    person can resolve, while a raised exception would fail the webhook GitHub is retrying.
    """
    task_ids = _implementation_task_ids_for_report(team_id, report_id)
    if str(task_id) not in task_ids:
        return 0
    older_task_ids = task_ids[: task_ids.index(str(task_id))]
    if not older_task_ids:
        return 0

    closed = 0
    pr_url_by_task = tasks_facade.get_latest_pr_url_by_task(older_task_ids)
    for older_task_id in older_task_ids:
        older_pr_url = pr_url_by_task.get(older_task_id)
        if not older_pr_url or older_pr_url == pr_url:
            continue
        if close_implementation_pr_for_report(
            team_id,
            report_id,
            reason="superseded",
            pr_url=older_pr_url,
            replacement_pr_url=pr_url,
        ):
            closed += 1
    return closed
