from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Exists, OuterRef, Q, QuerySet, Subquery

from posthog.dataclasses import frozen

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalReportArtefact, SignalReportAssignment

if TYPE_CHECKING:
    from posthog.models.user import User


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
