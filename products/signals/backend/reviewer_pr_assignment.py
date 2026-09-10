"""Add a report's opted-in suggested reviewers as GitHub assignees on its implementation PR.

A reviewer whose workflow is GitHub's "Assigned to me" never sees an inbox PR otherwise, because
every self-driving pull request opens with no assignee. Opt-in only, through
`SignalUserAutonomyConfig.github_assign_on_pull_request`, and best effort throughout: a GitHub
failure must never break the claim, sync, or reviewer edit that triggered it.
"""

from __future__ import annotations

import json

from django.db import transaction

import structlog

from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_generation.resolve_reviewers import (
    normalized_github_logins_from_reviewer_payloads,
    resolve_org_github_login_to_users,
)

logger = structlog.get_logger(__name__)

# Assign only while the pull request can still be reviewed. UNKNOWN is included because a PR whose
# state could not be read is far more often open than closed, and the task re-reads the real state
# from GitHub before it assigns.
ASSIGNABLE_PR_STATES = frozenset(
    {
        SignalReportAssignment.PrState.OPEN,
        SignalReportAssignment.PrState.DRAFT,
        SignalReportAssignment.PrState.UNKNOWN,
    }
)


def schedule_reviewer_pr_assignment(
    *,
    team_id: int,
    report_id: str,
    pr_url: str | None,
    pr_state: str | None,
) -> None:
    """Queue reviewer assignment for a report's pull request, after the current transaction commits.

    Enqueued on commit so nothing is assigned if the write rolls back, and so the GitHub calls run
    on a worker instead of holding up a claim, a PR sync, or a reviewer edit. `robust=True` keeps a
    broker outage from failing a write that already committed.
    """
    # A null state reads as unknown, the same way the rest of the assignment code reads the column,
    # so a row that never recorded a state is not silently skipped forever.
    if not pr_url or (pr_state or SignalReportAssignment.PrState.UNKNOWN) not in ASSIGNABLE_PR_STATES:
        return

    # noqa: PLC0415 because `tasks` imports this module for the task body, so a module-level
    # import here would be a cycle.
    from products.signals.backend.tasks import assign_reviewers_on_implementation_pr  # noqa: PLC0415

    transaction.on_commit(
        lambda: assign_reviewers_on_implementation_pr.delay(
            team_id=team_id,
            report_id=str(report_id),
            pr_url=pr_url,
        ),
        robust=True,
    )


def opted_in_reviewer_logins(*, team_id: int, report_id: str) -> list[str]:
    """GitHub logins of the report's current suggested reviewers who opted in to PR assignment.

    Reads only the latest `suggested_reviewers` row, which is the live reviewer set, so a reviewer
    removed from the list is not assigned on the next pull request event.
    """
    latest = (
        SignalReportArtefact.objects.filter(
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        )
        .order_by("-created_at")
        .first()
    )
    if latest is None:
        return []
    try:
        payloads = json.loads(latest.content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(payloads, list):
        return []

    logins = normalized_github_logins_from_reviewer_payloads(payloads)
    if not logins:
        return []
    login_to_user = resolve_org_github_login_to_users(team_id, logins)
    if not login_to_user:
        return []

    opted_in_user_ids = set(
        SignalUserAutonomyConfig.objects.filter(
            user_id__in={user.id for user in login_to_user.values()},
            github_assign_on_pull_request=True,
        ).values_list("user_id", flat=True)
    )
    return sorted(login for login, user in login_to_user.items() if user.id in opted_in_user_ids)


def assign_reviewers_to_pull_request(*, team_id: int, report_id: str, pr_url: str) -> list[str]:
    """Add the report's opted-in reviewers to its pull request. Returns the logins GitHub accepted.

    Never unassigns: GitHub's add-assignees endpoint is additive, so a reviewer somebody assigned by
    hand stays on the pull request. Returns an empty list when there is nothing to do or the call
    failed, and raises nothing.
    """
    if not SignalReport.objects.filter(id=report_id, team_id=team_id).exists():
        return []

    logins = opted_in_reviewer_logins(team_id=team_id, report_id=report_id)
    if not logins:
        return []

    parsed = GitHubIntegration.parse_pull_request_url(pr_url)
    if parsed is None:
        return []

    try:
        github = GitHubIntegration.first_for_team_repository(team_id, parsed.repository)
    except Exception:
        logger.exception(
            "signals.reviewer_pr_assignment.integration_lookup_failed",
            team_id=team_id,
            report_id=report_id,
            repository=parsed.repository,
        )
        return []
    if github is None:
        return []

    # A pull request closed or merged since the assignment was queued must not be reopened in
    # somebody's assigned list, so re-read the state here rather than trusting the queued snapshot.
    try:
        pr = github.get_pull_request(parsed.repository, parsed.number)
    except Exception:
        logger.exception(
            "signals.reviewer_pr_assignment.pr_fetch_failed",
            team_id=team_id,
            report_id=report_id,
            repository=parsed.repository,
            pr_number=parsed.number,
        )
        return []
    if not pr.get("success"):
        logger.warning(
            "signals.reviewer_pr_assignment.pr_fetch_failed",
            team_id=team_id,
            report_id=report_id,
            repository=parsed.repository,
            pr_number=parsed.number,
            error=pr.get("error"),
        )
        return []
    if pr.get("merged") or pr.get("state") == "closed":
        return []

    try:
        result = github.add_pull_request_assignees(parsed.repository, parsed.number, logins)
    except Exception:
        logger.exception(
            "signals.reviewer_pr_assignment.assign_failed",
            team_id=team_id,
            report_id=report_id,
            repository=parsed.repository,
            pr_number=parsed.number,
        )
        return []
    if not result.get("success"):
        logger.warning(
            "signals.reviewer_pr_assignment.assign_failed",
            team_id=team_id,
            report_id=report_id,
            repository=parsed.repository,
            pr_number=parsed.number,
            error=result.get("error"),
        )
        return []

    assigned = list(result.get("assignees") or [])
    # Counts only: GitHub logins are member PII and must not reach logs. A `requested` above
    # `assigned` means GitHub dropped a login, usually one without push access to the repository.
    logger.info(
        "signals.reviewer_pr_assignment.assigned",
        team_id=team_id,
        report_id=report_id,
        repository=parsed.repository,
        pr_number=parsed.number,
        requested=len(logins),
        assigned=len(assigned),
    )
    return assigned
