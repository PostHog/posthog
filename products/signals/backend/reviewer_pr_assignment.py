"""Put a person on a report's implementation PR as its GitHub assignee.

A reviewer whose workflow is GitHub's "Assigned to me" never sees an inbox PR otherwise, because
every self-driving pull request opens with no assignee. Two rules add assignees:

- A suggested reviewer who opted in through `SignalUserAutonomyConfig.github_assign_on_pull_request`
  is always added.
- A pull request that still has no assignee after that gets exactly one directly responsible
  individual (DRI): the person who claimed the report, else a random member of the GitHub team that
  owns the changed files (see `pr_owning_team.py`), else the most relevant suggested reviewer.
  A pull request that everybody could pick up is a pull request nobody picks up, and a wrong
  owner costs one reassignment. The `signals-pr-dri-assignee` flag rolls this rule out per
  organization.

Best effort throughout: a GitHub failure must never break the claim, sync, or reviewer edit that
triggered it.
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.db import transaction

import structlog

from posthog.models import Team
from posthog.models.github_integration_base import PullRequestRef
from posthog.models.integration import GitHubIntegration
from posthog.ph_client import feature_enabled_or_false

from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalUserAutonomyConfig,
)
from products.signals.backend.pr_owning_team import OwningTeam, OwningTeamResolver
from products.signals.backend.report_claims import get_active_claim, responsible_user
from products.signals.backend.report_generation.resolve_reviewers import (
    _normalized_reviewer_user_uuid,
    get_org_member_github_logins_by_user_uuid,
    normalized_github_logins_from_reviewer_payloads,
    resolve_org_github_login_to_users,
)

logger = structlog.get_logger(__name__)

PR_DRI_FEATURE_FLAG = "signals-pr-dri-assignee"

# Each DRI candidate costs one GitHub read. This covers the claimant and three other candidates,
# and stops a large team or a long scout reviewer list from turning one pull request into ten reads.
MAX_DRI_CHECKS = 4

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


def _latest_reviewer_rows(report_id: str) -> list[dict[str, Any]]:
    """The rows of the report's latest `suggested_reviewers` artefact, in their stored order.

    Only the latest row is the live reviewer set, so a reviewer removed from the list is not
    assigned on the next pull request event. The stored order is the relevance rank.
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
    return [row for row in payloads if isinstance(row, dict)]


def opted_in_reviewer_logins(*, team_id: int, report_id: str) -> list[str]:
    """GitHub logins of the report's current suggested reviewers who opted in to PR assignment."""
    logins = normalized_github_logins_from_reviewer_payloads(_latest_reviewer_rows(report_id))
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


def _pr_dri_enabled(team_id: int) -> bool:
    """Whether the organization has the DRI rule. On in DEBUG, and closed when the flag service fails."""
    if settings.DEBUG:
        return True
    try:
        organization_id = str(Team.objects.values_list("organization_id", flat=True).get(id=team_id))
        return feature_enabled_or_false(
            PR_DRI_FEATURE_FLAG,
            organization_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("signals.reviewer_pr_assignment.dri_flag_check_failed", team_id=team_id, exc_info=True)
        return False


def claimant_login(*, team_id: int, report_id: str) -> str | None:
    """The GitHub login of the person who claimed the report, when that person can be assigned."""
    claim = get_active_claim(team_id=team_id, report_id=report_id)
    claimant = responsible_user(claim) if claim is not None else None
    if claimant is None:
        return None
    return get_org_member_github_logins_by_user_uuid(team_id, [str(claimant.uuid)]).get(str(claimant.uuid))


def ranked_reviewer_logins(*, team_id: int, report_id: str) -> list[str]:
    """GitHub logins of the report's suggested reviewers, in their relevance order.

    A reviewer must be a member of the organization with a connected GitHub account, so a login
    from commit history that belongs to nobody in the organization is never assigned.
    """
    rows_with_uuid = [
        (row, _normalized_reviewer_user_uuid(row.get("user_uuid"))) for row in _latest_reviewer_rows(report_id)
    ]
    login_by_uuid = get_org_member_github_logins_by_user_uuid(team_id, [uuid for _, uuid in rows_with_uuid if uuid])
    # A row stored by uuid names the reviewer by that uuid, so its login is only read for a row without one.
    member_logins = resolve_org_github_login_to_users(
        team_id,
        normalized_github_logins_from_reviewer_payloads(row for row, uuid in rows_with_uuid if uuid is None),
    )

    candidates: list[str | None] = []
    for row, uuid in rows_with_uuid:
        if uuid is not None:
            candidates.append(login_by_uuid.get(uuid))
        else:
            login = str(row.get("github_login") or "").strip().lower()
            candidates.append(login if login in member_logins else None)
    return list(dict.fromkeys(login for login in candidates if login))


def _github_for_repository(*, team_id: int, report_id: str, repository: str) -> GitHubIntegration | None:
    """The team's GitHub integration for a repository, or None when there is none to call."""
    try:
        return GitHubIntegration.first_for_team_repository(team_id, repository)
    except Exception:
        logger.exception(
            "signals.reviewer_pr_assignment.integration_lookup_failed",
            team_id=team_id,
            report_id=report_id,
            repository=repository,
        )
        return None


def _assignable_pull_request(
    github: GitHubIntegration, *, team_id: int, report_id: str, parsed: PullRequestRef
) -> dict[str, Any] | None:
    """The pull request as GitHub reports it, or None when it no longer accepts assignees.

    A pull request closed or merged since the assignment was queued must not be reopened in
    somebody's assigned list, so this reads the state from GitHub rather than trusting the queued
    snapshot. A read that fails counts as not assignable.
    """
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
        return None
    if not pr.get("success"):
        logger.warning(
            "signals.reviewer_pr_assignment.pr_fetch_failed",
            team_id=team_id,
            report_id=report_id,
            repository=parsed.repository,
            pr_number=parsed.number,
            error=pr.get("error"),
        )
        return None
    if pr.get("merged") or pr.get("state") == "closed":
        return None
    return pr


def _add_assignees(
    github: GitHubIntegration, *, team_id: int, report_id: str, parsed: PullRequestRef, logins: list[str]
) -> list[str] | None:
    """Add the logins to the pull request.

    Returns the pull request's assignees as GitHub reports them after the call, an empty list when
    GitHub refused the call, and None when the outcome is unknown. A request that failed in transit
    may still have reached GitHub, so the caller must not assign anybody else on top of it.
    """
    log = logger.bind(team_id=team_id, report_id=report_id, repository=parsed.repository, pr_number=parsed.number)
    try:
        result = github.add_pull_request_assignees(parsed.repository, parsed.number, logins)
    except Exception:
        log.exception("signals.reviewer_pr_assignment.assign_failed")
        return None
    if not result.get("success"):
        log.warning("signals.reviewer_pr_assignment.assign_failed", error=result.get("error"))
        # The client reports a status code only for a response GitHub sent.
        return [] if result.get("status_code") is not None else None

    assigned = list(result.get("assignees") or [])
    # Counts only: GitHub logins are member PII and must not reach logs. A `requested` above
    # `assigned` means GitHub dropped a login, usually one without push access to the repository.
    log.info("signals.reviewer_pr_assignment.assigned", requested=len(logins), assigned=len(assigned))
    return assigned


def _first_assignable_login(
    github: GitHubIntegration, *, team_id: int, report_id: str, parsed: PullRequestRef, candidates: list[str]
) -> str | None:
    """The first candidate GitHub can assign in the repository, or None.

    The add-assignees call drops a login without push access instead of failing, so each candidate
    is checked with a read before the one write. A failed check stops the walk, because a GitHub
    error says nothing about whether the next candidate is a better owner.
    """
    log = logger.bind(team_id=team_id, report_id=report_id, repository=parsed.repository, pr_number=parsed.number)
    for login in candidates[:MAX_DRI_CHECKS]:
        try:
            result = github.is_assignable(parsed.repository, login)
        except Exception:
            log.exception("signals.reviewer_pr_assignment.assignable_check_failed")
            return None
        if not result.get("success"):
            log.warning("signals.reviewer_pr_assignment.assignable_check_failed", error=result.get("error"))
            return None
        if result.get("assignable"):
            return login
    log.info("signals.reviewer_pr_assignment.no_assignable_dri", candidates=len(candidates))
    return None


def _owning_team(
    github: GitHubIntegration, *, team_id: int, report_id: str, parsed: PullRequestRef
) -> OwningTeam | None:
    try:
        return OwningTeamResolver(github, team_id=team_id, report_id=report_id, parsed=parsed).resolve()
    except Exception:
        logger.exception(
            "signals.reviewer_pr_assignment.owning_team_failed",
            team_id=team_id,
            report_id=report_id,
            repository=parsed.repository,
            pr_number=parsed.number,
        )
        return None


def _was_unassigned_by_hand(github: GitHubIntegration, *, team_id: int, report_id: str, parsed: PullRequestRef) -> bool:
    """Whether somebody removed an assignee from the pull request. A failed read counts as yes.

    A person who unassigned the DRI made a decision, and a later report event must not undo it.
    """
    try:
        result = github.was_ever_unassigned(parsed.repository, parsed.number)
    except Exception:
        logger.exception("signals.reviewer_pr_assignment.events_fetch_failed", team_id=team_id, report_id=report_id)
        return True
    if not result.get("success"):
        logger.warning(
            "signals.reviewer_pr_assignment.events_fetch_failed",
            team_id=team_id,
            report_id=report_id,
            error=result.get("error"),
        )
        return True
    return bool(result.get("unassigned"))


def dri_candidate_logins(*, claimant: str | None, team: OwningTeam | None, reviewers: list[str]) -> list[str]:
    """GitHub logins that can own the pull request, the most responsible first.

    The claimant comes first, because to claim a report is to take the work on. The members of the
    team that owns the changed files come next. The suggested reviewers take their place when no
    ownership source names a team.
    """
    others = team.logins if team is not None and team.logins else reviewers
    return list(dict.fromkeys(login for login in (claimant, *others) if login))


def assign_reviewers_to_pull_request(*, team_id: int, report_id: str, pr_url: str) -> list[str]:
    """Put the report's opted-in reviewers, and one DRI when they do not own the code, on its pull request.

    Returns the pull request's assignees after the last call GitHub accepted. Never unassigns:
    GitHub's add-assignees endpoint is additive, so a person somebody assigned by hand stays on the
    pull request, and a pull request that somebody assigned or unassigned by hand gets no DRI.
    Returns an empty list when there is nothing to do or the call failed, and raises nothing.
    """
    if not SignalReport.objects.filter(id=report_id, team_id=team_id).exists():
        return []

    logins = opted_in_reviewer_logins(team_id=team_id, report_id=report_id)
    dri_enabled = _pr_dri_enabled(team_id)
    if not logins and not dri_enabled:
        return []

    parsed = GitHubIntegration.parse_pull_request_url(pr_url)
    if parsed is None:
        return []

    github = _github_for_repository(team_id=team_id, report_id=report_id, repository=parsed.repository)
    if github is None:
        return []

    pr = _assignable_pull_request(github, team_id=team_id, report_id=report_id, parsed=parsed)
    if pr is None:
        return []
    hand_assigned = bool(pr.get("assignees"))

    assigned = (
        _add_assignees(github, team_id=team_id, report_id=report_id, parsed=parsed, logins=logins) if logins else []
    )
    if assigned is None:
        return []
    if not dri_enabled or hand_assigned:
        return assigned

    claimant = claimant_login(team_id=team_id, report_id=report_id)
    team = _owning_team(github, team_id=team_id, report_id=report_id, parsed=parsed)
    # An opted-in reviewer owns the pull request only as its claimant or as a member of the owning
    # team. A reviewer who opted in is often suggested for other teams' code too.
    owners = {login.lower() for login in (claimant, *(team.logins if team else ())) if login}
    assigned_lower = {login.lower() for login in assigned}
    if assigned and (not owners or assigned_lower & owners):
        return assigned
    if _was_unassigned_by_hand(github, team_id=team_id, report_id=report_id, parsed=parsed):
        return assigned

    # One owner rather than every candidate, because each person on a shared assignment reads the
    # pull request as somebody else's job.
    candidates = dri_candidate_logins(
        claimant=claimant, team=team, reviewers=ranked_reviewer_logins(team_id=team_id, report_id=report_id)
    )
    dri = _first_assignable_login(
        github,
        team_id=team_id,
        report_id=report_id,
        parsed=parsed,
        candidates=[login for login in candidates if login not in assigned_lower],
    )
    if dri is None:
        return assigned
    return _add_assignees(github, team_id=team_id, report_id=report_id, parsed=parsed, logins=[dri]) or assigned
