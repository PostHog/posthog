"""Resolve implementation PR URLs linked to signal reports."""

import structlog

from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import SignalReport
from products.signals.backend.task_run_artefacts import SIGNALS_PRODUCT, TASK_RUN_TYPE_IMPLEMENTATION
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)


def fetch_implementation_pr_urls_for_reports(report_ids: list[str]) -> dict[str, str]:
    """PR URL from the latest implementation task run for each report, when available.

    The task↔report association comes from `SignalReport.associated_task_runs_for_reports` (the
    unified view of the `task_run` artefact log + legacy gate rows, batched over the whole page);
    the facade then resolves the latest PR-bearing run for each task, so multiple runs of a task
    collapse to the newest PR.
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

    pr_url_by_task = tasks_facade.get_latest_pr_url_by_task([task_id for _, task_id in pairs])

    result: dict[str, str] = {}
    for report_id, task_id in pairs:
        pr_url = pr_url_by_task.get(task_id)
        if pr_url and report_id not in result:
            result[report_id] = pr_url
    return result


# Left on the PR before it's closed, so anyone looking at the PR (not just whoever dismissed it,
# and regardless of where the dismissal came from) sees why it was closed and how to undo it.
_DISMISSAL_PR_COMMENT = (
    "🔕 Closing this PR because the linked PostHog report was dismissed.\n\n"
    "If that wasn't intended, restore the report in PostHog and reopen this PR."
)


def close_implementation_pr_for_report(team_id: int, report_id: str) -> bool:
    """Best-effort: comment on and close the GitHub PR opened for this report's implementation task.

    Called when a report is dismissed — a dismissed report means the fix isn't wanted, so the
    open PR shouldn't linger. Leaves an explanatory comment, then closes the PR. Returns True when
    the PR was closed, False when there was nothing to close or the close couldn't be completed.
    Never raises: dismissal must succeed regardless.
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

        # Explain first, close second — a failed comment shouldn't stop the close.
        comment_outcome = github.comment_on_pull_request(repository, pr_number, _DISMISSAL_PR_COMMENT)
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
