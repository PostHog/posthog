"""Assign ownership and request reviews on a report's implementation PR.

Somebody whose workflow is GitHub's "Assigned to me" never sees an inbox PR otherwise, because
every self-driving pull request opens with no assignee.

Under `signals-pr-dri-assignee`, an unassigned pull request gets at most one owner. Human claims
and protected reviewer lists take precedence. With the writer and research selection enabled,
a saved PR-specific relevance decision orders suitable candidates, with opted-in people first.
Otherwise the legacy policy uses owning-team membership and report reviewers.

Without the flag the older rule stands: every suggested reviewer who opted in through
`SignalUserAutonomyConfig.github_assign_on_pull_request` is added, and there is no DRI.

Suggested reviewers with a connected GitHub account receive review requests. The pull request
author, assignees, and existing requested reviewers are left alone.

Best effort throughout: a GitHub failure must never break the claim, sync, or reviewer edit that
triggered it.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import prefetch_related_objects

import structlog
from pydantic import ValidationError

from posthog.egress.limiter.policies import Priority
from posthog.models import Team
from posthog.models.github_integration_base import PullRequestRef
from posthog.models.integration import GitHubIntegration
from posthog.ph_client import feature_enabled_or_false

from products.signals.backend.artefact_schemas import TASK_RUN_TYPE_IMPLEMENTATION, TaskRunArtefact
from products.signals.backend.assignment_flags import (
    assignment_side_effects_allowed,
    assignment_side_effects_enabled,
    assignment_writer_enabled,
)
from products.signals.backend.assignment_service import ReportAssignmentService
from products.signals.backend.models import (
    SignalActorKind,
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalUserAutonomyConfig,
)
from products.signals.backend.pr_owner_decisions import PROwnerDecisionService
from products.signals.backend.pr_owner_selection import dri_candidate_logins, ordered_owner_logins
from products.signals.backend.pr_owning_team import OwningTeam, OwningTeamResolver
from products.signals.backend.report_claims import get_active_claim, responsible_user
from products.signals.backend.report_content_gates import team_research_reviewer_selection_enabled
from products.signals.backend.report_generation.resolve_reviewers import (
    _github_identity_prefetches,
    _normalized_reviewer_user_uuid,
    normalized_github_logins_from_reviewer_payloads,
    resolve_org_github_login_to_users,
    resolve_org_users_by_uuid,
)

logger = structlog.get_logger(__name__)

PR_DRI_FEATURE_FLAG = "signals-pr-dri-assignee"

# Each DRI candidate costs one GitHub read, so this stops a large team or a long scout reviewer
# list from turning one pull request into ten reads.
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


def _latest_reviewer_rows(*, team_id: int, report_id: str) -> list[dict[str, Any]]:
    """The rows of the report's latest `suggested_reviewers` artefact, in their stored order.

    Only the latest row is the live reviewer set, so a reviewer removed from the list is not
    assigned on the next pull request event. The stored order is the relevance rank.
    """
    latest = (
        SignalReportArtefact.objects.filter(
            team_id=team_id,
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
    logins = normalized_github_logins_from_reviewer_payloads(
        _latest_reviewer_rows(team_id=team_id, report_id=report_id)
    )
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
    if (
        user is None
        or not Team.objects.get(id=team_id).all_users_with_access().filter(id=user.id, is_active=True).exists()
    ):
        return None
    login = user.get_github_login(include_team_fallback=False)
    return login.lower() if login else None


def _has_human_claim(*, team_id: int, report_id: str) -> bool:
    claim = get_active_claim(team_id=team_id, report_id=report_id)
    if claim is None:
        return False
    return claim.actor_kind in (SignalActorKind.USER, SignalActorKind.AGENT) or (
        claim.actor_task_id is not None
        and _is_manual_implementation_task(team_id=team_id, report_id=report_id, task_id=claim.actor_task_id)
    )


def ranked_reviewer_logins(*, team_id: int, report_id: str) -> list[str]:
    """GitHub logins of the report's suggested reviewers, in their relevance order.

    A reviewer must be a member of the organization with a connected GitHub account, so a login
    from commit history that belongs to nobody in the organization is never assigned.
    """
    rows_with_uuid = [
        (row, _normalized_reviewer_user_uuid(row.get("user_uuid")))
        for row in _latest_reviewer_rows(team_id=team_id, report_id=report_id)
    ]
    if not rows_with_uuid:
        return []
    members_by_uuid = resolve_org_users_by_uuid(team_id, [uuid for _, uuid in rows_with_uuid if uuid])
    prefetch_related_objects(list(members_by_uuid.values()), *_github_identity_prefetches())
    # A row stored by uuid names the reviewer by that uuid, so its login is only read for a row without one.
    member_logins = resolve_org_github_login_to_users(
        team_id,
        normalized_github_logins_from_reviewer_payloads(row for row, uuid in rows_with_uuid if uuid is None),
    )
    candidate_uuids = {str(member.uuid) for member in [*members_by_uuid.values(), *member_logins.values()]}
    eligible_ids = set(
        Team.objects.get(id=team_id)
        .all_users_with_access(user_uuids=candidate_uuids)
        .filter(is_active=True)
        .values_list("id", flat=True)
    )
    login_by_uuid = {
        uuid: login.lower()
        for uuid, member in members_by_uuid.items()
        if member.id in eligible_ids and (login := member.get_github_login(include_team_fallback=False))
    }
    member_logins = {
        login: user
        for login, user in member_logins.items()
        if user.id in eligible_ids and (user.get_github_login(include_team_fallback=False) or "").lower() == login
    }

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
    github: GitHubIntegration,
    *,
    team_id: int,
    report_id: str,
    parsed: PullRequestRef,
    logins: list[str],
    require_delivery_flags: bool = False,
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
        if require_delivery_flags and not (assignment_side_effects_enabled(team_id)):
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
    require_delivery_flags: bool = False,
) -> list[str]:
    existing = {
        str(login).lower()
        for login in [pr.get("author"), *(pr.get("assignees") or []), *(pr.get("requested_reviewers") or [])]
        if login
    }
    wanted = [login for login in reviewers if login.lower() not in existing]
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
        if not assignment_side_effects_allowed(team_id=team_id, report_id=report_id):
            return []
        if require_delivery_flags and not (assignment_side_effects_enabled(team_id)):
            return []
        current_reviewers = set(ranked_reviewer_logins(team_id=team_id, report_id=report_id))
        wanted = [login for login in wanted if login in current_reviewers]
        if not wanted:
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


def ordered_owner_logins_for_reviewers(reviewers: list[str], opted_in: set[str]) -> list[str]:
    return [login for login in reviewers if login in opted_in] + [login for login in reviewers if login not in opted_in]


def _assign_relevant_owner(
    github: GitHubIntegration, *, team_id: int, report_id: str, parsed: PullRequestRef, pr: dict[str, Any]
) -> list[str]:
    log = logger.bind(team_id=team_id, report_id=report_id)
    if not pr.get("head_sha") or not pr.get("base_sha"):
        log.warning("signals.pr_owner.scope_lookup_failed")
        return []
    service = PROwnerDecisionService(team_id=team_id, report_id=report_id, github=github)
    snapshot = ReportAssignmentService.read_for_report(team_id=team_id, report_id=report_id)
    inputs = service.inputs(
        repository=parsed.repository, pr_number=parsed.number, head_sha=pr["head_sha"], base_sha=pr["base_sha"]
    )
    if snapshot.control == "human" or snapshot.state != inputs.report_state:
        log.info("signals.pr_owner.human_protected")
        return []
    selected = service.prepare(inputs, snapshot)
    if selected is None or selected.decision.outcome != "selected":
        return []
    eligible = service.eligible_logins(selected)
    candidates = [
        login for login in ordered_owner_logins(selected.decision, eligible.opted_in) if login in eligible.logins
    ]
    dri = _first_assignable_login(github, team_id=team_id, report_id=report_id, parsed=parsed, candidates=candidates)
    if dri is None:
        return []

    current_eligible = service.eligible_logins(selected)
    if dri not in current_eligible.logins or current_eligible.opted_in != eligible.opted_in:
        log.info("signals.pr_owner.access_changed")
        return []
    current_pr = _assignable_pull_request(github, team_id=team_id, report_id=report_id, parsed=parsed)
    if current_pr is None or current_pr.get("assignees"):
        return []
    if _was_unassigned_by_hand(github, team_id=team_id, report_id=report_id, parsed=parsed):
        return []
    current = service.inputs(
        repository=parsed.repository,
        pr_number=parsed.number,
        head_sha=current_pr.get("head_sha") or "",
        base_sha=current_pr.get("base_sha") or "",
    )
    if not service.same_scope(inputs, current) or _has_human_claim(team_id=team_id, report_id=report_id):
        log.info("signals.pr_owner.stale")
        return []
    if not (
        _pr_dri_enabled(team_id)
        and assignment_writer_enabled(team_id)
        and team_research_reviewer_selection_enabled(team_id)
        and assignment_side_effects_enabled(team_id)
        and assignment_side_effects_allowed(team_id=team_id, report_id=report_id)
    ):
        log.info("signals.pr_owner.application_disabled")
        return []
    return (
        _add_assignees(
            github, team_id=team_id, report_id=report_id, parsed=parsed, logins=[dri], require_delivery_flags=True
        )
        or []
    )


def _assign_one_dri(
    github: GitHubIntegration,
    *,
    team_id: int,
    report_id: str,
    parsed: PullRequestRef,
    pr: dict[str, Any],
    opted_in: set[str],
    reviewers: list[str],
    require_delivery_flags: bool = False,
) -> list[str]:
    """Put exactly one directly responsible individual on a pull request that has none.

    A pull request somebody already assigned has an owner, and a pull request somebody unassigned by
    hand was a decision a later report event must not undo. Both are left alone.
    """
    if pr.get("assignees"):
        return []
    if _was_unassigned_by_hand(github, team_id=team_id, report_id=report_id, parsed=parsed):
        return []

    try:
        snapshot = ReportAssignmentService.read_for_report(team_id=team_id, report_id=report_id)
        claimant = human_claimant_login(team_id=team_id, report_id=report_id)
        if claimant is None and _has_human_claim(team_id=team_id, report_id=report_id):
            logger.info("signals.pr_owner.claimant_unavailable", team_id=team_id, report_id=report_id)
            return []
        if snapshot.control == "human":
            logger.info("signals.pr_owner.human_protected", team_id=team_id, report_id=report_id)
            # A PR-specific choice must not restore a reviewer removed on this same report.
            if not reviewers or (claimant is not None and claimant not in reviewers):
                logger.info("signals.pr_owner.human_protected", team_id=team_id, report_id=report_id)
                return []
            candidates = [claimant] if claimant else ordered_owner_logins_for_reviewers(reviewers, opted_in)
        elif claimant:
            candidates = [claimant]
        elif assignment_writer_enabled(team_id) and team_research_reviewer_selection_enabled(team_id):
            return _assign_relevant_owner(github, team_id=team_id, report_id=report_id, parsed=parsed, pr=pr)
        else:
            logger.info("signals.pr_owner.legacy_policy", team_id=team_id, report_id=report_id)
            candidates = dri_candidate_logins(
                claimant=None,
                opted_in=opted_in,
                team=_owning_team(github, team_id=team_id, report_id=report_id, parsed=parsed),
                reviewers=reviewers,
            )
    except Exception as error:
        logger.warning(
            "signals.pr_owner.lookup_failed", team_id=team_id, report_id=report_id, error_type=type(error).__name__
        )
        return []

    dri = _first_assignable_login(github, team_id=team_id, report_id=report_id, parsed=parsed, candidates=candidates)
    if dri is None:
        return []
    current_pr = _assignable_pull_request(github, team_id=team_id, report_id=report_id, parsed=parsed)
    if (
        current_pr is None
        or current_pr.get("assignees")
        or _was_unassigned_by_hand(github, team_id=team_id, report_id=report_id, parsed=parsed)
    ):
        return []
    current = ReportAssignmentService.read_for_report(team_id=team_id, report_id=report_id)
    if current.state != snapshot.state or not assignment_side_effects_allowed(team_id=team_id, report_id=report_id):
        return []
    if claimant != human_claimant_login(team_id=team_id, report_id=report_id) or (
        claimant is None and _has_human_claim(team_id=team_id, report_id=report_id)
    ):
        return []
    if snapshot.control == "human" and dri not in ranked_reviewer_logins(team_id=team_id, report_id=report_id):
        return []
    return (
        _add_assignees(
            github,
            team_id=team_id,
            report_id=report_id,
            parsed=parsed,
            logins=[dri],
            require_delivery_flags=require_delivery_flags,
        )
        or []
    )


def assign_reviewers_to_pull_request(*, team_id: int, report_id: str, pr_url: str) -> list[str]:
    """Request reviews and assign one DRI under the flag, else every opted-in reviewer.

    Returns the assignees GitHub accepted. Never unassigns: the add-assignees endpoint is additive,
    so a person somebody assigned by hand stays on the pull request. Returns an empty list when
    there is nothing to do or the call failed, and raises nothing.
    """
    if not assignment_side_effects_allowed(team_id=team_id, report_id=report_id):
        return []

    if not SignalReport.objects.filter(id=report_id, team_id=team_id).exists():
        return []

    reviewers = ranked_reviewer_logins(team_id=team_id, report_id=report_id)
    logins = [login for login in opted_in_assignee_logins(team_id=team_id, report_id=report_id) if login in reviewers]
    dri_enabled = _pr_dri_enabled(team_id)
    relevance_enabled = (
        dri_enabled and assignment_writer_enabled(team_id) and team_research_reviewer_selection_enabled(team_id)
    )
    if relevance_enabled and not (assignment_side_effects_enabled(team_id)):
        return []
    if not reviewers and not logins and not dri_enabled:
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

    if dri_enabled:
        assigned = _assign_one_dri(
            github,
            team_id=team_id,
            report_id=report_id,
            parsed=parsed,
            pr=pr,
            opted_in=set(logins),
            reviewers=reviewers,
            require_delivery_flags=relevance_enabled,
        )
    else:
        assigned = (
            _add_assignees(github, team_id=team_id, report_id=report_id, parsed=parsed, logins=logins) or []
            if logins
            else []
        )

    if not assignment_side_effects_allowed(team_id=team_id, report_id=report_id) or (
        relevance_enabled and not (assignment_side_effects_enabled(team_id))
    ):
        return assigned
    current_pr = _assignable_pull_request(github, team_id=team_id, report_id=report_id, parsed=parsed)
    if current_pr is None:
        return assigned
    _request_reviews(
        github,
        team_id=team_id,
        report_id=report_id,
        parsed=parsed,
        pr={**current_pr, "assignees": [*(current_pr.get("assignees") or []), *assigned]},
        reviewers=ranked_reviewer_logins(team_id=team_id, report_id=report_id),
        require_delivery_flags=relevance_enabled,
    )
    return assigned
