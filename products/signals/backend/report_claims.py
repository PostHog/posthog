from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from django.db.models import Exists, OuterRef, Q, QuerySet, Subquery

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalReportArtefact, SignalReportAssignment
from products.tasks.backend.facade import api as tasks_facade


@frozen
class ReportClaim:
    claim_id: UUID
    report_id: UUID
    team_id: int
    actor_kind: str | None
    actor_user: User | None
    actor_task_id: UUID | None
    actor_agent: str | None
    claimed_at: datetime

    @property
    def actor_user_id(self) -> int | None:
        return self.actor_user.id if self.actor_user else None


def claim_from_artefact(claim: SignalReportArtefact) -> ReportClaim:
    return ReportClaim(
        claim_id=claim.id,
        report_id=claim.report_id,
        team_id=claim.team_id,
        actor_kind=claim.actor_kind,
        actor_user=claim.created_by,
        actor_task_id=claim.task_id,
        actor_agent=claim.actor_agent,
        claimed_at=claim.created_at,
    )


def active_claims(*, team_id: int) -> QuerySet[SignalReportArtefact]:
    claims = SignalReportArtefact.objects.filter(team_id=team_id, type="work_claim")
    latest = claims.filter(report_id=OuterRef("report_id")).order_by("-created_at", "-id").values("id")[:1]
    releases = SignalReportArtefact.objects.filter(
        team_id=team_id, report_id=OuterRef("report_id"), type="work_release", claim_id=OuterRef("id")
    )
    return claims.filter(id=Subquery(latest)).alias(released=Exists(releases)).filter(released=False)


def legacy_claims(*, team_id: int) -> QuerySet[SignalReportAssignment]:
    history = SignalReportArtefact.objects.filter(team_id=team_id, type="work_claim").values("report_id")
    return SignalReportAssignment.all_teams.filter(team_id=team_id, actor_kind__isnull=False).exclude(
        report_id__in=history
    )


def get_active_claims(*, team_id: int, report_ids: list[str]) -> dict[str, ReportClaim]:
    result = {
        str(row.report_id): claim_from_artefact(row)
        for row in active_claims(team_id=team_id).filter(report_id__in=report_ids).select_related("created_by")
    }
    for row in legacy_claims(team_id=team_id).filter(report_id__in=report_ids).select_related("actor_user"):
        result[str(row.report_id)] = ReportClaim(
            claim_id=row.id,
            report_id=row.report_id,
            team_id=row.team_id,
            actor_kind=row.actor_kind,
            actor_user=row.actor_user,
            actor_task_id=row.actor_task_id,
            actor_agent=row.actor_agent,
            claimed_at=row.claimed_at or row.created_at,
        )
    return result


def get_active_claim(*, team_id: int, report_id: str | UUID) -> ReportClaim | None:
    return get_active_claims(team_id=team_id, report_ids=[str(report_id)]).get(str(report_id))


def responsible_user(claim: ReportClaim) -> User | None:
    """The PostHog user who answers for a claim, or None when no person stands behind it.

    A user claim and an external agent claim carry the user. An internal task claim carries only
    the task, and the task runs as the user who started it, so that user answers for the claim.
    """
    if claim.actor_user is not None:
        return claim.actor_user
    if claim.actor_task_id is None:
        return None
    tasks = tasks_facade.get_tasks_by_ids([claim.actor_task_id], [claim.team_id])
    if not tasks or tasks[0].created_by_id is None:
        return None
    return User.objects.filter(id=tasks[0].created_by_id).first()


def responsible_users(claims: Iterable[ReportClaim]) -> dict[UUID, User]:
    """`responsible_user` for many claims in a fixed number of queries, keyed by claim id."""
    claims = list(claims)
    result = {claim.claim_id: claim.actor_user for claim in claims if claim.actor_user is not None}
    task_claims = [claim for claim in claims if claim.actor_user is None and claim.actor_task_id is not None]
    if not task_claims:
        return result
    creator_by_task = tasks_facade.get_task_creator_ids(
        [claim.actor_task_id for claim in task_claims if claim.actor_task_id is not None],
        {claim.team_id for claim in task_claims},
    )
    users = User.objects.in_bulk(set(creator_by_task.values()))
    for claim in task_claims:
        creator_id = creator_by_task.get(str(claim.actor_task_id))
        if creator_id in users:
            result[claim.claim_id] = users[creator_id]
    return result


def reports_claimed_for_user(*, team_id: int, user_id: int) -> Q:
    """Reports the user claimed, themselves or through their external agents.

    Internal task claims do not count: auto-start runs tasks as a suggested reviewer who never took the work on.
    """
    own_claims = active_claims(team_id=team_id).filter(created_by_id=user_id)
    own_legacy = legacy_claims(team_id=team_id).filter(actor_user_id=user_id)
    return Q(id__in=own_claims.values("report_id")) | Q(id__in=own_legacy.values("report_id"))


def reports_with_active_claim(*, team_id: int, actor: ArtefactAttribution | None = None) -> Q:
    claims = active_claims(team_id=team_id)
    legacy = legacy_claims(team_id=team_id)
    if actor is not None:
        claims = claims.filter(actor_kind=actor.kind, created_by_id=actor.user_id, actor_agent=actor.agent_name)
        claims = claims.filter(task_id=actor.task_id) if actor.task_id else claims.filter(task_id__isnull=True)
        legacy = legacy.filter(
            actor_kind=actor.kind,
            actor_user_id=actor.user_id,
            actor_task_id=actor.task_id,
            actor_agent=actor.agent_name,
        )
    return Q(id__in=claims.values("report_id")) | Q(id__in=legacy.values("report_id"))


def actor_owns_claim(claim: ReportClaim, actor: ArtefactAttribution) -> bool:
    return (
        claim.actor_kind == actor.kind
        and claim.actor_user_id == actor.user_id
        and (str(claim.actor_task_id) if claim.actor_task_id else None) == actor.task_id
        and claim.actor_agent == actor.agent_name
    )


def actor_can_release_claim(claim: ReportClaim, actor: ArtefactAttribution) -> bool:
    return actor_owns_claim(claim, actor) or (
        actor.kind == "user"
        and actor.user_id is not None
        and claim.actor_kind == "agent"
        and claim.actor_user_id == actor.user_id
    )


def is_user_claim_of(claim: ReportClaim, user_id: int | None) -> bool:
    """Whether a person holds the claim directly, not through an agent or an internal task."""
    return claim.actor_kind == "user" and user_id is not None and claim.actor_user_id == user_id


def is_user_claim_of_task_creator(claim: ReportClaim, task_id: str) -> bool:
    """Whether the person holding the claim started the task, so the task works under their claim."""
    if claim.actor_kind != "user":
        return False
    tasks = tasks_facade.get_tasks_by_ids([task_id], [claim.team_id])
    return bool(tasks) and is_user_claim_of(claim, tasks[0].created_by_id)


def actor_works_under_claim(claim: ReportClaim, actor: ArtefactAttribution) -> bool:
    """Whether the actor can resume the claim and add work to it. Only the owner can release it."""
    return actor_owns_claim(claim, actor) or (
        actor.task_id is not None and is_user_claim_of_task_creator(claim, actor.task_id)
    )
