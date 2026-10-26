"""Apply report assignments and request reviews on implementation pull requests.

With research selection and the assignment writer enabled, the first eligible saved report
reviewer becomes the PR's single owner. Personal preferences and GitHub access checks can
reject a person but never select someone outside the report.
Manual GitHub assignments and removals remain authoritative.

Other projects retain the legacy DRI and opt-in policies. Task execution permission is
separate from report and PR assignment. GitHub failures must not break report writes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog
from pydantic import ValidationError

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.event_usage import groups
from posthog.models import Team
from posthog.models.github_integration_base import PullRequestRef
from posthog.models.integration import GitHubIntegration
from posthog.ph_client import feature_enabled_or_false, ph_scoped_capture

from products.signals.backend.artefact_schemas import (
    TASK_RUN_TYPE_IMPLEMENTATION,
    PROwnerAssignment,
    PROwnerIdentityProof,
    SuggestedReviewerEntry,
    TaskRunArtefact,
)
from products.signals.backend.assignment_flags import (
    assignment_side_effects_allowed,
    assignment_side_effects_enabled,
    assignment_writer_enabled,
)
from products.signals.backend.models import (
    SignalActorKind,
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalUserAutonomyConfig,
)
from products.signals.backend.pr_owner_assignments import PROwnerAssignmentService, PROwnerOrigin
from products.signals.backend.pr_owning_team import OwningTeam, OwningTeamResolver
from products.signals.backend.report_claims import get_active_claim, responsible_user
from products.signals.backend.report_content_gates import team_research_reviewer_selection_enabled
from products.signals.backend.report_generation.resolve_reviewers import (
    _github_identity_prefetches,
    _normalized_reviewer_user_uuid,
    get_org_member_github_logins_by_user_uuid,
    normalized_github_logins_from_reviewer_payloads,
    resolve_org_github_login_to_users,
)
from products.signals.backend.reviewer_rules import ReviewerRules, contains_reviewer

if TYPE_CHECKING:
    from products.signals.backend.reviewer_rules import ReviewerSnapshot

logger = structlog.get_logger(__name__)

PR_DRI_FEATURE_FLAG = "signals-pr-dri-assignee"

# Each DRI candidate costs one GitHub read, so this stops a large team or a long scout reviewer
# list from turning one pull request into ten reads.
MAX_DRI_CHECKS = 4
MAX_REPORT_ASSIGNEE_CHECKS = 10

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
    if not assignment_side_effects_allowed(team_id=team_id, report_id=report_id):
        return

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
        .order_by("-created_at", "-id")
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


def opted_in_assignee_logins(*, team_id: int, report_id: str) -> list[str]:
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


def _is_manual_implementation_task(*, team_id: int, report_id: str, task_id: UUID) -> bool:
    """Whether a person started the implementation task, rather than auto-start creating it.

    Auto-start stamps the branch it generated onto the run artefact, and a manual start leaves it
    unset, so only a run without one is somebody's decision. Anything unreadable counts as
    automatic, because a claim nobody can vouch for must not outrank the team that owns the code.
    """
    rows = SignalReportArtefact.objects.filter(
        team_id=team_id,
        report_id=report_id,
        type=SignalReportArtefact.ArtefactType.TASK_RUN,
        task_id=task_id,
    )
    for row in rows:
        try:
            content = TaskRunArtefact.model_validate_json(row.content)
        except ValidationError:
            continue
        if content.type == TASK_RUN_TYPE_IMPLEMENTATION and content.automation_branch is None:
            return True
    return False


def human_claimant_login(*, team_id: int, report_id: str) -> str | None:
    """The GitHub login of the person who chose to work on the report, when they can be assigned.

    A claim a person made counts, and so does one their agent made for them, because an agent claim
    carries the person it ran as. A task claim counts only when a person started that task: an
    auto-started task runs as the report's top suggested reviewer, so it names a commit-history
    guess rather than a decision.
    """
    claim = get_active_claim(team_id=team_id, report_id=report_id)
    if claim is None:
        return None
    if claim.actor_kind in (SignalActorKind.USER, SignalActorKind.AGENT):
        user = claim.actor_user
    elif claim.actor_task_id is not None and _is_manual_implementation_task(
        team_id=team_id, report_id=report_id, task_id=claim.actor_task_id
    ):
        user = responsible_user(claim)
    else:
        return None
    if user is None:
        return None
    user_uuid = str(user.uuid)
    if not (Team.objects.get(id=team_id).all_users_with_access(user_uuids=[user_uuid]).filter(is_active=True).exists()):
        return None
    return get_org_member_github_logins_by_user_uuid(team_id, [user_uuid]).get(user_uuid)


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
    user_uuids = [uuid for _, uuid in rows_with_uuid if uuid] + [str(user.uuid) for user in member_logins.values()]
    if not user_uuids:
        return []
    eligible_uuids = {
        str(uuid)
        for uuid in Team.objects.get(id=team_id)
        .all_users_with_access(user_uuids=user_uuids)
        .filter(is_active=True)
        .values_list("uuid", flat=True)
    }

    candidates: list[str | None] = []
    for row, uuid in rows_with_uuid:
        if uuid is not None:
            candidates.append(login_by_uuid.get(uuid) if uuid in eligible_uuids else None)
        else:
            login = str(row.get("github_login") or "").strip().lower()
            member = member_logins.get(login)
            candidates.append(login if member is not None and str(member.uuid) in eligible_uuids else None)
    return list(dict.fromkeys(login for login in candidates if login))


def _github_for_repository(*, team_id: int, report_id: str, repository: str) -> GitHubIntegration | None:
    """The team's GitHub integration for a repository, or None when there is none to call."""
    try:
        return GitHubIntegration.first_for_team_repository(
            team_id, repository, source="signals_reviewers", priority=Priority.BATCH
        )
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
        if not assignment_side_effects_allowed(team_id=team_id, report_id=report_id):
            return None
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


def _request_reviews(
    github: GitHubIntegration,
    *,
    team_id: int,
    report_id: str,
    parsed: PullRequestRef,
    pr: dict[str, Any],
    reviewers: list[str],
) -> list[str]:
    assignees = list(dict.fromkeys(str(login).lower() for login in (pr.get("assignees") or []) if login))
    owner = assignees[0] if len(assignees) == 1 else None
    if owner is None and (pr.get("requested_reviewers") or pr.get("requested_teams")):
        return []

    existing = {str(login).lower() for login in [pr.get("author"), *(pr.get("requested_reviewers") or [])] if login}
    candidates = [owner] if owner else reviewers
    wanted = [login for login in candidates if login.lower() not in existing]
    if not wanted:
        return []

    log = logger.bind(team_id=team_id, report_id=report_id, repository=parsed.repository, pr_number=parsed.number)
    try:
        reviews = github.list_submitted_pull_request_reviewers(parsed.repository, parsed.number)
    except Exception:
        log.exception("signals.reviewer_pr_assignment.reviews_fetch_failed")
        return []
    if not reviews.get("success"):
        log.warning("signals.reviewer_pr_assignment.reviews_fetch_failed", error=reviews.get("error"))
        return []
    existing.update(str(login).lower() for login in (reviews.get("reviewed_by") or []) if login)
    wanted = [login for login in wanted if login.lower() not in existing]
    if not wanted:
        return []
    try:
        removed = github.get_removed_pull_request_reviewers(parsed.repository, parsed.number)
    except Exception:
        log.exception("signals.reviewer_pr_assignment.removed_reviews_fetch_failed")
        return []
    if removed is None:
        log.warning("signals.reviewer_pr_assignment.removed_reviews_fetch_failed")
        return []
    wanted = [login for login in wanted if login.lower() not in removed][:1]
    if not wanted:
        return []

    try:
        if not assignment_side_effects_allowed(team_id=team_id, report_id=report_id):
            return []
        result = github.request_pull_request_reviews(parsed.repository, parsed.number, wanted)
    except Exception:
        log.exception("signals.reviewer_pr_assignment.review_request_failed")
        return []
    if not result.get("success"):
        log.warning("signals.reviewer_pr_assignment.review_request_failed", error=result.get("error"))
        return []

    requested = list(result.get("requested_reviewers") or [])
    log.info("signals.reviewer_pr_assignment.reviews_requested", requested=len(wanted), accepted=len(requested))
    return requested


@frozen
class AssignableOwner:
    login: str
    identity: PROwnerIdentityProof | None


@frozen
class OwnerApplicationState:
    allowed: bool
    previous: PROwnerAssignment | None
    reason: str


def _assignable_owners(
    github: GitHubIntegration,
    *,
    team_id: int,
    report_id: str,
    parsed: PullRequestRef,
    candidates: list[str],
    assignments: PROwnerAssignmentService,
    limit: int | None = None,
    first_only: bool = False,
) -> list[AssignableOwner] | None:
    """Candidates whose repository access and linked identity GitHub verifies."""
    log = logger.bind(team_id=team_id, report_id=report_id, repository=parsed.repository, pr_number=parsed.number)
    bounded_candidates = candidates[:limit] if limit is not None else candidates
    identities = assignments.identities_for(bounded_candidates)
    owners: list[AssignableOwner] = []
    for login in bounded_candidates:
        identity = identities[login]
        try:
            result = github.is_assignable(parsed.repository, login)
        except Exception:
            log.exception("signals.reviewer_pr_assignment.assignable_check_failed")
            return None
        if not result.get("success"):
            log.warning("signals.reviewer_pr_assignment.assignable_check_failed", error=result.get("error"))
            return None
        if not result.get("assignable"):
            continue
        if not identity.linked_user:
            owners.append(AssignableOwner(login=login, identity=None))
            if first_only:
                return owners
            continue
        if identity.proof is None:
            log.info("signals.pr_owner.identity_unverified")
            continue
        try:
            permission = github.get_collaborator_permission(
                parsed.repository,
                login,
                expected_user_id=identity.proof.github_user_id,
            )
        except Exception:
            log.exception("signals.pr_owner.identity_check_failed")
            return None
        if permission in {"admin", "write"}:
            owners.append(AssignableOwner(login=login, identity=identity.proof))
            if first_only:
                return owners
    return owners


def _owner_application_state(
    github: GitHubIntegration,
    *,
    team_id: int,
    report_id: str,
    parsed: PullRequestRef,
    pr: dict[str, Any],
    assignments: PROwnerAssignmentService,
) -> OwnerApplicationState:
    current = {str(login).lower() for login in pr.get("assignees") or []}
    previous = assignments.latest()
    if previous is not None:
        automatic = {owner.login for owner in previous.owners}
        if current == automatic:
            return OwnerApplicationState(allowed=True, previous=previous, reason="automatic_owners")
        reason = "manually_unassigned" if not current else "assignees_changed"
        return OwnerApplicationState(allowed=False, previous=previous, reason=reason)
    if current:
        return OwnerApplicationState(allowed=False, previous=None, reason="unknown_assignment_origin")
    if _was_unassigned_by_hand(github, team_id=team_id, report_id=report_id, parsed=parsed):
        return OwnerApplicationState(allowed=False, previous=None, reason="manually_unassigned")
    return OwnerApplicationState(allowed=True, previous=None, reason="unassigned")


def _capture_owner_reassessment(
    *,
    team_id: int,
    report_id: str,
    previous: PROwnerAssignment,
    outcome: str,
    reason: str,
    origin: PROwnerOrigin | None = None,
    verified_count: int = 0,
) -> None:
    try:
        team = Team.objects.select_related("organization").get(id=team_id)
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=str(team.organization_id),
                event="signals_pr_owner_reassessed",
                properties={
                    "team_id": team_id,
                    "report_id": report_id,
                    "outcome": outcome,
                    "reason": reason,
                    "previous_origin": previous.origin,
                    "previous_owner_count": len(previous.owners),
                    **({"origin": origin} if origin else {}),
                    "identity_verified_count": verified_count,
                },
                groups=groups(organization=team.organization, team=team),
            )
    except Exception:
        logger.exception("signals.pr_owner.reassessment_capture_failed", team_id=team_id, report_id=report_id)


def _remove_assignees(
    github: GitHubIntegration,
    *,
    team_id: int,
    report_id: str,
    parsed: PullRequestRef,
    logins: list[str],
) -> list[str] | None:
    try:
        result = github.remove_pull_request_assignees(parsed.repository, parsed.number, logins)
    except Exception:
        logger.exception("signals.pr_owner.unassign_failed", team_id=team_id, report_id=report_id)
        return None
    if not result.get("success"):
        logger.warning(
            "signals.pr_owner.unassign_failed",
            team_id=team_id,
            report_id=report_id,
            error=result.get("error"),
        )
        return [] if result.get("status_code") is not None else None
    return [str(login).lower() for login in result.get("assignees") or []]


def _apply_automatic_owners(
    github: GitHubIntegration,
    *,
    team_id: int,
    report_id: str,
    parsed: PullRequestRef,
    assignments: PROwnerAssignmentService,
    application: OwnerApplicationState,
    owners: list[AssignableOwner],
    origin: PROwnerOrigin,
) -> list[str]:
    previous = application.previous
    previous_logins = [owner.login for owner in previous.owners] if previous else []
    wanted = [owner.login for owner in owners]
    previous_set = set(previous_logins)
    wanted_set = set(wanted)
    identities = {owner.login: owner.identity for owner in owners}
    verified_count = sum(identity is not None for identity in identities.values())

    if previous_set == wanted_set:
        if previous is not None and any(
            owner.proof is not None and owner.proof.expires_at <= timezone.now() for owner in previous.owners
        ):
            assignments.record(identities=identities, origin=origin)
        if previous is not None:
            _capture_owner_reassessment(
                team_id=team_id,
                report_id=report_id,
                previous=previous,
                outcome="unchanged",
                reason="same_candidates",
                origin=origin,
                verified_count=verified_count,
            )
        return []

    added = [login for login in wanted if login not in previous_set]
    if added:
        assigned = _add_assignees(github, team_id=team_id, report_id=report_id, parsed=parsed, logins=added)
        expected = previous_set | set(added)
        if assigned is None or {login.lower() for login in assigned} != expected:
            if assigned is not None:
                _remove_assignees(github, team_id=team_id, report_id=report_id, parsed=parsed, logins=added)
            if previous is not None:
                _capture_owner_reassessment(
                    team_id=team_id,
                    report_id=report_id,
                    previous=previous,
                    outcome="protected",
                    reason="assignees_changed_during_reassessment",
                    origin=origin,
                    verified_count=verified_count,
                )
            return []

    removed = [login for login in previous_logins if login not in wanted_set]
    if removed:
        remaining = _remove_assignees(github, team_id=team_id, report_id=report_id, parsed=parsed, logins=removed)
        if remaining is None or set(remaining) != wanted_set:
            if added:
                _remove_assignees(github, team_id=team_id, report_id=report_id, parsed=parsed, logins=added)
            if previous is not None:
                _capture_owner_reassessment(
                    team_id=team_id,
                    report_id=report_id,
                    previous=previous,
                    outcome="protected",
                    reason="assignees_changed_during_reassessment",
                    origin=origin,
                    verified_count=verified_count,
                )
            return []

    assignments.record(identities=identities, origin=origin, replaced_logins=previous_logins)
    if previous is not None:
        _capture_owner_reassessment(
            team_id=team_id,
            report_id=report_id,
            previous=previous,
            outcome="reassigned",
            reason="candidates_changed",
            origin=origin,
            verified_count=verified_count,
        )
    return added


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


def dri_candidate_logins(
    *, claimant: str | None, opted_in: set[str], team: OwningTeam | None, reviewers: list[str]
) -> list[str]:
    """GitHub logins that can be the DRI, the most responsible first.

    In order: the person who chose the work, then somebody who asked to be assigned, then a member
    of the team that owns the changed files. The suggested reviewers are the owners only when no
    ownership source names a team.

    Among those who opted in, an owning-team member comes first. Among the owning team, commit
    history gives no priority, so one prolific committer does not get every pull request.
    """
    team_logins = list(team.logins) if team is not None and team.logins else []
    owners = team_logins or reviewers
    opted_in_ranked = [login for login in reviewers if login in opted_in]

    candidates = [claimant]
    candidates += [login for login in opted_in_ranked if login in team_logins]
    candidates += opted_in_ranked
    candidates += owners
    return list(dict.fromkeys(login for login in candidates if login))


def _report_assignee_logins(team: Team, snapshot: ReviewerSnapshot, *, require_opt_in: bool = True) -> list[str]:
    linked = resolve_org_github_login_to_users(
        team.id, [entry.github_login for entry in snapshot.reviewers if entry.github_login and not entry.user_uuid]
    )
    identities = [
        entry.model_copy(update={"user_uuid": str(member.uuid)})
        if not entry.user_uuid and entry.github_login and (member := linked.get(entry.github_login.lower()))
        else entry
        for entry in snapshot.reviewers
    ]
    uuids = [entry.user_uuid for entry in identities if entry.user_uuid]
    if not uuids:
        return []
    members = (
        team.all_users_with_access(user_uuids=uuids)
        .filter(is_active=True)
        .prefetch_related(*_github_identity_prefetches())
    )
    if require_opt_in:
        members = members.filter(signal_autonomy_config__github_assign_on_pull_request=True)
    logins = {
        str(member.uuid): login.lower()
        for member in members
        if (login := member.get_github_login(include_team_fallback=False))
    }
    return list(
        dict.fromkeys(
            login
            for entry in identities
            if entry.user_uuid
            and (login := logins.get(entry.user_uuid))
            and not contains_reviewer(snapshot.corrections.excluded, entry)
        )
    )


def _assign_report_reviewers(
    github: GitHubIntegration, *, team_id: int, report_id: str, parsed: PullRequestRef, pr: dict[str, Any]
) -> list[str]:
    assignments = PROwnerAssignmentService(
        team_id=team_id,
        report_id=report_id,
        repository=parsed.repository,
        pr_number=parsed.number,
    )
    application = _owner_application_state(
        github,
        team_id=team_id,
        report_id=report_id,
        parsed=parsed,
        pr=pr,
        assignments=assignments,
    )
    if not application.allowed:
        if application.previous is not None:
            _capture_owner_reassessment(
                team_id=team_id,
                report_id=report_id,
                previous=application.previous,
                outcome="protected",
                reason=application.reason,
            )
        return []

    log = logger.bind(team_id=team_id, report_id=report_id)
    try:
        team = Team.objects.get(id=team_id)
        snapshot = ReviewerRules.read_for_report(team_id=team_id, report_id=report_id)
        if snapshot.corrections.needs_review:
            return []
        candidates = _report_assignee_logins(team, snapshot)
        if len(candidates) < len(snapshot.reviewers):
            log.info(
                "signals.reviewer_pr_assignment.unavailable_accounts",
                selected=len(snapshot.reviewers),
                linked=len(candidates),
            )
        owners = _assignable_owners(
            github,
            team_id=team_id,
            report_id=report_id,
            parsed=parsed,
            candidates=candidates,
            assignments=assignments,
            limit=MAX_REPORT_ASSIGNEE_CHECKS,
            first_only=True,
        )
        if owners is None:
            return []

        current_pr = _assignable_pull_request(github, team_id=team_id, report_id=report_id, parsed=parsed)
        if current_pr is None:
            return []
        current_application = _owner_application_state(
            github,
            team_id=team_id,
            report_id=report_id,
            parsed=parsed,
            pr=current_pr,
            assignments=assignments,
        )
        if not current_application.allowed or current_application.previous != application.previous:
            return []
        current = ReviewerRules.read_for_report(team_id=team_id, report_id=report_id)
        if current.state != snapshot.state or _report_assignee_logins(team, current) != candidates:
            return []
        if not (
            assignment_writer_enabled(team_id)
            and team_research_reviewer_selection_enabled(team_id)
            and assignment_side_effects_enabled(team_id)
        ):
            return []
        return _apply_automatic_owners(
            github,
            team_id=team_id,
            report_id=report_id,
            parsed=parsed,
            assignments=assignments,
            application=current_application,
            owners=owners,
            origin="report",
        )
    except Exception:
        log.exception("signals.reviewer_pr_assignment.report_assignment_failed")
        return []


def assign_reviewers_to_pull_request(*, team_id: int, report_id: str, pr_url: str) -> list[str]:
    """Apply the shared report assignment, or the legacy DRI/opt-in policy, and request reviews.

    Returns newly added assignees. An empty result can also mean a recorded automatic owner
    was cleared. Manual assignments remain authoritative.
    """
    if not assignment_side_effects_allowed(team_id=team_id, report_id=report_id):
        return []

    if not SignalReport.objects.filter(id=report_id, team_id=team_id).exists():
        return []

    shared_assignment = assignment_writer_enabled(team_id) and team_research_reviewer_selection_enabled(team_id)
    if shared_assignment and not assignment_side_effects_enabled(team_id):
        return []
    logins = [] if shared_assignment else opted_in_assignee_logins(team_id=team_id, report_id=report_id)
    reviewers = ranked_reviewer_logins(team_id=team_id, report_id=report_id)
    dri_enabled = _pr_dri_enabled(team_id)
    if not reviewers and not logins and not dri_enabled and not shared_assignment:
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

    if shared_assignment:
        assigned = _assign_report_reviewers(github, team_id=team_id, report_id=report_id, parsed=parsed, pr=pr)
    elif dri_enabled:
        assigned = _assign_one_dri(
            github,
            team_id=team_id,
            report_id=report_id,
            parsed=parsed,
            pr=pr,
            opted_in=set(logins),
            reviewers=reviewers,
        )
    else:
        assigned = (
            _add_assignees(github, team_id=team_id, report_id=report_id, parsed=parsed, logins=logins) or []
            if logins
            else []
        )

    if shared_assignment:
        if not (
            assignment_writer_enabled(team_id)
            and team_research_reviewer_selection_enabled(team_id)
            and assignment_side_effects_enabled(team_id)
        ):
            return assigned
        try:
            snapshot = ReviewerRules.read_for_report(team_id=team_id, report_id=report_id)
            if snapshot.corrections.needs_review:
                return assigned
            reviewers = _report_assignee_logins(Team.objects.get(id=team_id), snapshot, require_opt_in=False)
        except Exception:
            logger.exception(
                "signals.reviewer_pr_assignment.reviewers_lookup_failed", team_id=team_id, report_id=report_id
            )
            return assigned
        current_pr = _assignable_pull_request(github, team_id=team_id, report_id=report_id, parsed=parsed)
        if current_pr is None:
            return assigned
        pr = current_pr
    _request_reviews(
        github,
        team_id=team_id,
        report_id=report_id,
        parsed=parsed,
        pr={**pr, "assignees": [*(pr.get("assignees") or []), *assigned]},
        reviewers=reviewers,
    )
    return assigned


def _assign_one_dri(
    github: GitHubIntegration,
    *,
    team_id: int,
    report_id: str,
    parsed: PullRequestRef,
    pr: dict[str, Any],
    opted_in: set[str],
    reviewers: list[str],
) -> list[str]:
    """Assign one DRI, replacing only a prior owner this worker recorded."""
    assignments = PROwnerAssignmentService(
        team_id=team_id,
        report_id=report_id,
        repository=parsed.repository,
        pr_number=parsed.number,
    )
    application = _owner_application_state(
        github,
        team_id=team_id,
        report_id=report_id,
        parsed=parsed,
        pr=pr,
        assignments=assignments,
    )
    if not application.allowed:
        if application.previous is not None:
            _capture_owner_reassessment(
                team_id=team_id,
                report_id=report_id,
                previous=application.previous,
                outcome="protected",
                reason=application.reason,
            )
        return []

    snapshot = ReviewerRules.read_for_report(team_id=team_id, report_id=report_id)
    if snapshot.corrections.needs_review:
        return []
    claimant = human_claimant_login(team_id=team_id, report_id=report_id)
    candidates = dri_candidate_logins(
        claimant=claimant,
        opted_in=opted_in,
        team=_owning_team(github, team_id=team_id, report_id=report_id, parsed=parsed),
        reviewers=reviewers,
    )
    members = resolve_org_github_login_to_users(team_id, candidates)
    candidates = [
        login
        for login in candidates
        if not contains_reviewer(
            snapshot.corrections.excluded,
            SuggestedReviewerEntry(
                github_login=login, user_uuid=str(members[login].uuid) if login in members else None
            ),
        )
    ]
    owners = _assignable_owners(
        github,
        team_id=team_id,
        report_id=report_id,
        parsed=parsed,
        candidates=candidates,
        assignments=assignments,
        limit=MAX_DRI_CHECKS,
        first_only=True,
    )
    if not owners:
        return []
    owner = owners[0]
    current_pr = _assignable_pull_request(github, team_id=team_id, report_id=report_id, parsed=parsed)
    if current_pr is None:
        return []
    current_application = _owner_application_state(
        github,
        team_id=team_id,
        report_id=report_id,
        parsed=parsed,
        pr=current_pr,
        assignments=assignments,
    )
    if not current_application.allowed or current_application.previous != application.previous:
        return []
    current = ReviewerRules.read_for_report(team_id=team_id, report_id=report_id)
    if (
        current.state != snapshot.state
        or human_claimant_login(team_id=team_id, report_id=report_id) != claimant
        or ranked_reviewer_logins(team_id=team_id, report_id=report_id) != reviewers
    ):
        return []
    return _apply_automatic_owners(
        github,
        team_id=team_id,
        report_id=report_id,
        parsed=parsed,
        assignments=assignments,
        application=current_application,
        owners=[owner],
        origin="claim" if claimant == owner.login else "legacy",
    )
