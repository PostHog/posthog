import logging
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count, F, FilteredRelation, Q
from django.utils import timezone

from asgiref.sync import async_to_sync
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.models import Team

from products.growth.backend.facade.api import start_account_audit
from products.growth.backend.models import AccountAuditAdmission, AccountAuditCredential
from products.signals.backend.facade.api import resolve_audit_actor_for_team
from products.skills.backend.facade.api import get_skill_prompt
from products.workflows.backend.facade.api import is_workflow_staff_controlled

COOLDOWN = timedelta(days=7)
PROJECT_ACTIVITY_WINDOW = timedelta(days=30)
logger = logging.getLogger(__name__)


@frozen
class AccountAuditRequest:
    organization_id: UUID
    team_id: int | None
    reason: str
    skill_name: str


@frozen
class AccountAuditResult:
    status: Literal["accepted", "invalid", "unauthorized", "forbidden", "conflict", "cooldown", "unavailable"]
    workflow_id: UUID | None = None
    team_id: int | None = None
    next_available_at: datetime | None = None


class AccountAuditService:
    @staticmethod
    def signing_secret_for(public_key_id: UUID) -> str | None:
        return (
            AccountAuditCredential.objects.filter(public_key_id=public_key_id, is_active=True)
            .values_list("signing_secret", flat=True)
            .first()
        )

    @classmethod
    def start(cls, payload: AccountAuditRequest, public_key_id: UUID, webhook_id: str) -> AccountAuditResult:
        credential = AccountAuditCredential.objects.select_related("owner").filter(public_key_id=public_key_id).first()
        if credential is None or not cls._credential_is_eligible(credential):
            return AccountAuditResult(status="unauthorized")
        team_id = cls._resolve_team_id(payload, credential_id=credential.id, webhook_id=webhook_id)
        if team_id is None:
            return AccountAuditResult(status="invalid")
        if not cls._ai_processing_is_approved(payload.organization_id):
            return AccountAuditResult(status="forbidden")
        actor_id = resolve_audit_actor_for_team(team_id)
        if actor_id is None:
            return AccountAuditResult(status="forbidden")
        skill = get_skill_prompt(team_id=settings.GROWTH_ENRICHMENT_INTERNAL_TEAM_ID, skill_name=payload.skill_name)
        if skill is None or not skill.body.strip():
            return AccountAuditResult(status="invalid")
        admission, admission_status = cls._admit(
            credential=credential,
            webhook_id=webhook_id,
            organization_id=payload.organization_id,
            team_id=team_id,
            reason=payload.reason,
            skill_name=payload.skill_name,
        )
        if admission_status == "cooldown":
            return AccountAuditResult(
                status="cooldown", next_available_at=(admission.dispatched_at or admission.created_at) + COOLDOWN
            )
        if admission_status != "accepted":
            return AccountAuditResult(status="conflict")
        try:
            async_to_sync(start_account_audit)(
                organization_id=str(payload.organization_id),
                team_id=team_id,
                user_id=actor_id,
                workflow_id=str(admission.workflow_id),
                reason=admission.reason,
                skill_name=admission.skill_name,
            )
        except WorkflowAlreadyStartedError as error:
            if error.workflow_id != str(admission.workflow_id):
                logger.warning("account_audit_workflow_id_conflict", extra={"admission_id": admission.id})
                return AccountAuditResult(status="unavailable")
        except Exception:
            logger.exception("account_audit_workflow_dispatch_failed", extra={"admission_id": admission.id})
            return AccountAuditResult(status="unavailable")
        AccountAuditAdmission.objects.for_team(team_id).filter(pk=admission.pk, dispatched_at__isnull=True).update(
            dispatched_at=timezone.now()
        )
        return AccountAuditResult(status="accepted", workflow_id=admission.workflow_id, team_id=team_id)

    @classmethod
    def retry_pending_dispatches(cls) -> None:
        pending = (
            AccountAuditAdmission.objects.unscoped()
            .filter(
                dispatched_at__isnull=True,
                credential__is_active=True,
                created_at__lt=timezone.now() - timedelta(minutes=1),
            )
            .select_related("credential")
            .order_by("created_at")[:100]
        )
        for admission in pending:
            cls.start(
                AccountAuditRequest(
                    organization_id=admission.organization_id,
                    team_id=admission.team_id,
                    reason=admission.reason,
                    skill_name=admission.skill_name,
                ),
                public_key_id=admission.credential.public_key_id,
                webhook_id=admission.webhook_id,
            )

    @staticmethod
    def _resolve_team_id(request: AccountAuditRequest, *, credential_id: int, webhook_id: str) -> int | None:
        teams = Team.objects.filter(organization_id=request.organization_id).exclude(project__is_pending_deletion=True)
        team_id = request.team_id
        if team_id is None:
            team_id = (
                AccountAuditAdmission.objects.unscoped()
                .filter(credential_id=credential_id, webhook_id=webhook_id, organization_id=request.organization_id)
                .values_list("team_id", flat=True)
                .first()
            )
        if team_id is not None:
            return teams.filter(id=team_id).values_list("id", flat=True).first()
        return (
            teams.filter(id=F("project_id"), parent_team__isnull=True, is_demo=False)
            .alias(
                recent_views=FilteredRelation(
                    "filesystemviewlog",
                    condition=Q(filesystemviewlog__viewed_at__gte=timezone.now() - PROJECT_ACTIVITY_WINDOW),
                )
            )
            .values("id", "project__created_at")
            .annotate(recent_active_users=Count("recent_views__user_id", distinct=True))
            .order_by("-recent_active_users", "project__created_at", "id")
            .values_list("id", flat=True)
            .first()
        )

    @staticmethod
    def _credential_is_eligible(credential: AccountAuditCredential) -> bool:
        return (
            credential.is_active
            and credential.owner is not None
            and credential.owner.is_active
            and credential.owner.is_staff
            and is_workflow_staff_controlled(
                workflow_id=credential.workflow_id,
                team_id=settings.GROWTH_ENRICHMENT_INTERNAL_TEAM_ID,
                owner_id=credential.owner.id,
            )
        )

    @staticmethod
    def _ai_processing_is_approved(organization_id: UUID) -> bool:
        return Team.objects.filter(
            organization_id=organization_id, organization__is_ai_data_processing_approved=True
        ).exists()

    @staticmethod
    def _admit(
        *,
        credential: AccountAuditCredential,
        webhook_id: str,
        organization_id: UUID,
        team_id: int,
        reason: str,
        skill_name: str,
    ) -> tuple[AccountAuditAdmission, str]:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"growth-audit:{organization_id}"]
                )
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    [f"growth-audit-delivery:{credential.id}:{webhook_id}"],
                )
            existing = (
                AccountAuditAdmission.objects.unscoped().filter(credential=credential, webhook_id=webhook_id).first()
            )
            if existing is not None:
                if (
                    existing.organization_id == organization_id
                    and existing.team_id == team_id
                    and existing.reason == reason
                    and existing.skill_name == skill_name
                ):
                    return existing, "accepted"
                return existing, "conflict"
            recent = (
                AccountAuditAdmission.objects.unscoped()
                .filter(organization_id=organization_id)
                .filter(Q(dispatched_at__gt=timezone.now() - COOLDOWN) | Q(dispatched_at__isnull=True))
                .order_by("-created_at")
                .first()
            )
            if recent is not None:
                return recent, "cooldown"
            admission = AccountAuditAdmission.objects.for_team(team_id).create(
                credential=credential,
                webhook_id=webhook_id,
                organization_id=organization_id,
                team_id=team_id,
                reason=reason,
                skill_name=skill_name,
            )
        return admission, "accepted"
