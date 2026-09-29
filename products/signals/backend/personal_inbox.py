"""The personal Inbox: which reports belong to a viewer, what they can do next, and in what order.

The reports list applies this policy for `scope=for_me` and `sort=relevance`, so the web app,
Desktop and MCP read one selection and one order. Selection is a SQL filter, so counts and pages
see the same rows. Order and explanation come from `decide`, so a row's position and its stated
reason cannot disagree.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import datetime

from django.db import models
from django.db.models import Q, QuerySet

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.signals.backend.implementation_pr import ImplementationPr, fetch_implementation_prs_for_reports
from products.signals.backend.models import (
    AutonomyPriority,
    SignalReport,
    SignalReportArtefact,
    SignalReportPullRequest,
)
from products.signals.backend.report_claims import ReportClaim, active_claims, get_active_claims, legacy_claims
from products.signals.backend.report_generation.research import ActionabilityChoice
from products.signals.backend.suggested_reviewer_index import report_ids_naming_reviewers
from products.tasks.backend.facade import api as tasks_facade

POLICY_VERSION = "personal-inbox-v1"
PERSONAL_INBOX_FEATURE_FLAG = "signals-personal-inbox"

# A personal Inbox is much smaller than this. The cap keeps one request bounded if it is not.
MAX_RELEVANCE_CANDIDATES = 1000

# Dismissed, resolved, and snoozed reports (snoozing returns a report to `potential`) stay out of
# the active personal Inbox. An explicit `status` or `view` filter still reaches them.
ACTIVE_PERSONAL_STATUSES = frozenset(
    {
        SignalReport.Status.READY,
        SignalReport.Status.PENDING_INPUT,
        SignalReport.Status.IN_PROGRESS,
        SignalReport.Status.FAILED,
    }
)

_CLOSED_STATUSES = frozenset(
    {SignalReport.Status.RESOLVED, SignalReport.Status.SUPPRESSED, SignalReport.Status.DELETED}
)
_RESEARCH_STATUSES = frozenset(
    {SignalReport.Status.POTENTIAL, SignalReport.Status.CANDIDATE, SignalReport.Status.IN_PROGRESS}
)
_ACTIVE_PR_STATES = frozenset(
    {
        SignalReportPullRequest.State.OPEN,
        SignalReportPullRequest.State.DRAFT,
        SignalReportPullRequest.State.UNKNOWN,
    }
)
# Approved or changes-requested PRs wait on their author, not on another review.
_REVIEWABLE_DECISIONS = frozenset({None, SignalReportPullRequest.ReviewDecision.REVIEW_REQUIRED})


class PersonalReason(models.TextChoices):
    SUGGESTED_REVIEWER = "suggested_reviewer", "Suggested reviewer"
    CLAIMED = "claimed", "Claimed"


class PersonalActionState(models.TextChoices):
    ACTION_AVAILABLE = "action_available", "Action available"
    WAITING = "waiting", "Waiting"
    UNKNOWN = "unknown", "Unknown"
    CLOSED = "closed", "Closed"


class PersonalNextActionKind(models.TextChoices):
    REVIEW_FINDING = "review_finding", "Review the finding"
    ANSWER_QUESTION = "answer_question", "Answer the question"
    REVIEW_PR = "review_pr", "Review the pull request"
    CHECK_PR = "check_pr", "Check the pull request"
    RESOLVE_BLOCKER = "resolve_blocker", "Resolve the blocker"
    CONTINUE_WORK = "continue_work", "Continue the work"


class ClaimHolder(models.TextChoices):
    VIEWER = "viewer"
    VIEWER_TASK = "viewer_task"
    OTHER = "other"


_ACTION_STATE_RANK = {
    PersonalActionState.ACTION_AVAILABLE: 0,
    PersonalActionState.UNKNOWN: 1,
    PersonalActionState.WAITING: 2,
    PersonalActionState.CLOSED: 3,
}
_PRIORITY_RANK = {priority: index for index, priority in enumerate(AutonomyPriority.values)}


@frozen
class ReportFacts:
    """What the policy knows about one report, from the viewer's side."""

    report_id: str
    status: str
    actionability: str | None
    already_addressed: bool | None
    priority: str | None
    updated_at: datetime
    changed_at: datetime
    names_viewer: bool
    claim_holder: ClaimHolder | None
    pull_requests: tuple[ImplementationPr, ...]
    viewer_id: int


@frozen
class PersonalNextAction:
    kind: PersonalNextActionKind
    pull_request_url: str | None = None


@frozen
class PersonalDecision:
    report_id: str
    reasons: tuple[PersonalReason, ...]
    action_state: PersonalActionState
    next_action: PersonalNextAction | None
    # When the facts behind `action_state` were last observed. None when nobody verified them.
    observed_at: datetime | None
    urgent: bool
    priority: str | None
    changed_at: datetime

    def sort_key(self) -> tuple[int, int, int, int, float, str]:
        responsibility = 0 if PersonalReason.CLAIMED in self.reasons else 1 if self.reasons else 2
        return (
            0 if self.urgent else 1,
            _ACTION_STATE_RANK[self.action_state],
            _PRIORITY_RANK.get(self.priority or "", len(_PRIORITY_RANK)),
            responsibility,
            -self.changed_at.timestamp(),
            self.report_id,
        )


def personal_inbox_enabled(user: User, organization_id: str) -> bool:
    return (
        posthoganalytics.feature_enabled(
            PERSONAL_INBOX_FEATURE_FLAG,
            str(user.distinct_id),
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            send_feature_flag_events=False,
        )
        is True
    )


def _viewer_github_logins(user: User) -> list[str]:
    login = user.get_github_login()
    return [login.lower()] if login else []


def _reports_naming_viewer(team_id: int, user: User) -> QuerySet:
    # The viewer's own login is in hand, so it matches an entry either way, as `is_suggested_reviewer` does.
    return report_ids_naming_reviewers(
        team_id=team_id,
        user_uuids=[str(user.uuid)],
        github_logins=_viewer_github_logins(user),
        logins_match_unidentified_only=False,
    )


def _reviewer_is_relevant(status: str, actionability: str | None) -> bool:
    # Matches `is_suggested_reviewer`: a failed pipeline or a report judged not actionable asks
    # nothing of a reviewer.
    if status == SignalReport.Status.FAILED:
        return False
    return not (status == SignalReport.Status.READY and actionability == ActionabilityChoice.NOT_ACTIONABLE.value)


def personal_inbox_filter(*, team_id: int, user: User) -> Q:
    """Reports that name the viewer as a relevant reviewer, or that the viewer claimed.

    A claim held by an internal task counts for the user who created the task, because the task
    runs as that user. Project membership alone never selects a report.
    """
    reviewer = (
        Q(id__in=_reports_naming_viewer(team_id, user))
        & ~Q(status=SignalReport.Status.FAILED)
        & ~Q(status=SignalReport.Status.READY, latest_actionability=ActionabilityChoice.NOT_ACTIONABLE.value)
    )
    viewer_tasks = tasks_facade.task_ids_created_by_subquery(team_id, user.id)
    claims = active_claims(team_id=team_id).filter(Q(created_by_id=user.id) | Q(task_id__in=viewer_tasks))
    legacy = legacy_claims(team_id=team_id).filter(Q(actor_user_id=user.id) | Q(actor_task_id__in=viewer_tasks))
    return reviewer | Q(id__in=claims.values("report_id")) | Q(id__in=legacy.values("report_id"))


def _claim_holders(team_id: int, user: User, claims: dict[str, ReportClaim | None]) -> dict[str, ClaimHolder]:
    live = {report_id: claim for report_id, claim in claims.items() if claim is not None}
    unowned_task_ids = {
        claim.actor_task_id for claim in live.values() if claim.actor_user is None and claim.actor_task_id is not None
    }
    task_creators = {
        str(task.id): task.created_by_id for task in tasks_facade.get_tasks_by_ids(unowned_task_ids, [team_id])
    }
    holders: dict[str, ClaimHolder] = {}
    for report_id, claim in live.items():
        if claim.actor_user is not None:
            holders[report_id] = ClaimHolder.VIEWER if claim.actor_user.id == user.id else ClaimHolder.OTHER
        elif claim.actor_task_id is not None and task_creators.get(str(claim.actor_task_id)) == user.id:
            holders[report_id] = ClaimHolder.VIEWER_TASK
        else:
            holders[report_id] = ClaimHolder.OTHER
    return holders


def _latest_priorities(team_id: int, report_ids: list[str]) -> dict[str, str]:
    rows = (
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id__in=report_ids,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
        )
        .order_by("report_id", "-created_at")
        .distinct("report_id")
        .values_list("report_id", "content")
    )
    priorities: dict[str, str] = {}
    for report_id, content in rows:
        priority = _parse_priority(content)
        if priority is not None:
            priorities[str(report_id)] = priority
    return priorities


def _parse_priority(content: str | None) -> str | None:
    try:
        data = json.loads(content or "")
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    value = data.get("priority") if isinstance(data, dict) else None
    return value if value in _PRIORITY_RANK else None


def load_report_facts(
    reports: Sequence[SignalReport],
    *,
    team_id: int,
    user: User,
    claims: dict[str, ReportClaim | None] | None = None,
    pull_requests: dict[str, list[ImplementationPr]] | None = None,
) -> list[ReportFacts]:
    """Batch-load the facts for these reports. Pass the claim and PR maps a caller already holds."""
    report_ids = [str(report.id) for report in reports]
    if not report_ids:
        return []
    if claims is None:
        claims = dict.fromkeys(report_ids) | get_active_claims(team_id=team_id, report_ids=report_ids)
    if pull_requests is None:
        pull_requests = fetch_implementation_prs_for_reports(report_ids, team_id=team_id)
    holders = _claim_holders(team_id, user, claims)
    priorities = _latest_priorities(team_id, report_ids)
    naming_viewer = {
        str(report_id)
        for report_id in _reports_naming_viewer(team_id, user)
        .filter(report_id__in=report_ids)
        .values_list("report_id", flat=True)
    }
    return [
        ReportFacts(
            report_id=str(report.id),
            status=report.status,
            actionability=report.latest_actionability,
            already_addressed=report.latest_already_addressed,
            priority=priorities.get(str(report.id)),
            updated_at=report.updated_at,
            changed_at=report.last_run_at or report.promoted_at or report.created_at,
            names_viewer=str(report.id) in naming_viewer,
            claim_holder=holders.get(str(report.id)),
            pull_requests=tuple(pull_requests.get(str(report.id), [])),
            viewer_id=user.id,
        )
        for report in reports
    ]


def decide(facts: ReportFacts) -> PersonalDecision:
    reasons: list[PersonalReason] = []
    if facts.names_viewer and _reviewer_is_relevant(facts.status, facts.actionability):
        reasons.append(PersonalReason.SUGGESTED_REVIEWER)
    if facts.claim_holder in (ClaimHolder.VIEWER, ClaimHolder.VIEWER_TASK):
        reasons.append(PersonalReason.CLAIMED)

    action_state, next_action, evidence_pr = _next_step(facts, is_reviewer=PersonalReason.SUGGESTED_REVIEWER in reasons)
    observed_at = evidence_pr.checked_at if evidence_pr is not None else facts.updated_at
    return PersonalDecision(
        report_id=facts.report_id,
        reasons=tuple(reasons),
        action_state=action_state,
        next_action=next_action,
        observed_at=observed_at,
        urgent=facts.priority == AutonomyPriority.P0 and action_state != PersonalActionState.WAITING,
        priority=facts.priority,
        changed_at=facts.changed_at,
    )


def _viewer_claims(facts: ReportFacts) -> bool:
    return facts.claim_holder in (ClaimHolder.VIEWER, ClaimHolder.VIEWER_TASK)


def _next_step(
    facts: ReportFacts, *, is_reviewer: bool
) -> tuple[PersonalActionState, PersonalNextAction | None, ImplementationPr | None]:
    if facts.status in _CLOSED_STATUSES:
        return PersonalActionState.CLOSED, None, None
    if facts.status == SignalReport.Status.FAILED:
        if _viewer_claims(facts):
            return (
                PersonalActionState.ACTION_AVAILABLE,
                PersonalNextAction(kind=PersonalNextActionKind.RESOLVE_BLOCKER),
                None,
            )
        return PersonalActionState.UNKNOWN, None, None
    if facts.status in _RESEARCH_STATUSES:
        return PersonalActionState.WAITING, None, None
    if (
        facts.status == SignalReport.Status.PENDING_INPUT
        and facts.actionability == ActionabilityChoice.REQUIRES_HUMAN_INPUT.value
        and (is_reviewer or _viewer_claims(facts))
    ):
        return (
            PersonalActionState.ACTION_AVAILABLE,
            PersonalNextAction(kind=PersonalNextActionKind.ANSWER_QUESTION),
            None,
        )

    # Every linked PR counts: one merged layer of a stack does not finish the others.
    active = [pr for pr in facts.pull_requests if pr.state in _ACTIVE_PR_STATES]
    awaiting_review = [
        pr
        for pr in active
        if pr.state == SignalReportPullRequest.State.OPEN
        and pr.review_decision in _REVIEWABLE_DECISIONS
        and not (pr.attached_by_user is not None and pr.attached_by_user.id == facts.viewer_id)
    ]
    if is_reviewer and not _viewer_claims(facts) and awaiting_review:
        pr = awaiting_review[0]
        return (
            PersonalActionState.ACTION_AVAILABLE,
            PersonalNextAction(kind=PersonalNextActionKind.REVIEW_PR, pull_request_url=pr.url),
            pr,
        )
    unknown = [pr for pr in active if pr.state == SignalReportPullRequest.State.UNKNOWN]
    if unknown:
        pr = unknown[0]
        return (
            PersonalActionState.UNKNOWN,
            PersonalNextAction(kind=PersonalNextActionKind.CHECK_PR, pull_request_url=pr.url),
            pr,
        )
    if active:
        return PersonalActionState.WAITING, None, active[0]
    merged = [pr for pr in facts.pull_requests if pr.state == SignalReportPullRequest.State.MERGED]
    if merged:
        # The report stays open until completion is verified, so nothing is asked of the viewer.
        return PersonalActionState.WAITING, None, merged[0]

    if facts.claim_holder in (ClaimHolder.OTHER, ClaimHolder.VIEWER_TASK):
        return PersonalActionState.WAITING, None, None
    if facts.claim_holder == ClaimHolder.VIEWER:
        return PersonalActionState.ACTION_AVAILABLE, PersonalNextAction(kind=PersonalNextActionKind.CONTINUE_WORK), None
    if facts.already_addressed:
        return PersonalActionState.UNKNOWN, None, None
    if facts.status == SignalReport.Status.READY and _reviewer_is_relevant(facts.status, facts.actionability):
        return (
            PersonalActionState.ACTION_AVAILABLE,
            PersonalNextAction(kind=PersonalNextActionKind.REVIEW_FINDING),
            None,
        )
    return PersonalActionState.UNKNOWN, None, None


def decide_reports(
    reports: Sequence[SignalReport],
    *,
    team_id: int,
    user: User,
    claims: dict[str, ReportClaim | None] | None = None,
    pull_requests: dict[str, list[ImplementationPr]] | None = None,
) -> dict[str, PersonalDecision]:
    facts = load_report_facts(reports, team_id=team_id, user=user, claims=claims, pull_requests=pull_requests)
    return {fact.report_id: decide(fact) for fact in facts}


def rank_report_ids(decisions: Iterable[PersonalDecision]) -> list[str]:
    return [decision.report_id for decision in sorted(decisions, key=PersonalDecision.sort_key)]


_FACT_FIELDS = (
    "id",
    "team_id",
    "status",
    "latest_actionability",
    "latest_already_addressed",
    "created_at",
    "updated_at",
    "promoted_at",
    "last_run_at",
)


@frozen
class RankedInbox:
    report_ids: list[str]
    decisions: dict[str, PersonalDecision]
    truncated: bool


def rank_personal_inbox(queryset: QuerySet[SignalReport], *, team_id: int, user: User) -> RankedInbox:
    """Order every report the filtered list selects, so pagination cuts an already-ranked list."""
    candidates = list(
        queryset.order_by("-updated_at", "id")
        .select_related(None)
        .prefetch_related(None)
        .only(*_FACT_FIELDS)[: MAX_RELEVANCE_CANDIDATES + 1]
    )
    decisions = decide_reports(candidates[:MAX_RELEVANCE_CANDIDATES], team_id=team_id, user=user)
    return RankedInbox(
        report_ids=rank_report_ids(decisions.values()),
        decisions=decisions,
        truncated=len(candidates) > MAX_RELEVANCE_CANDIDATES,
    )
