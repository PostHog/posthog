import json
import base64
import logging
import binascii
from datetime import timedelta
from uuid import UUID

from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.ingress.verify.schemes import HmacSha256, VerificationOutcome
from posthog.models import Team
from posthog.rate_limit import IPThrottle

from products.growth.backend.facade.api import start_account_audit
from products.growth.backend.models import AccountAuditAdmission, AccountAuditCredential
from products.signals.backend.facade.api import resolve_audit_actor_for_team
from products.skills.backend.facade.api import get_skill_prompt
from products.workflows.backend.facade.api import is_workflow_active_for_owner

MAX_BODY_BYTES = 4 * 1024
SIGNATURE_TOLERANCE = timedelta(minutes=5)
COOLDOWN = timedelta(days=7)
SOURCE_TEAM_ID = 2
logger = logging.getLogger(__name__)


@frozen
class AccountAuditRequest:
    organization_id: UUID
    team_id: int | None
    reason: str
    skill_name: str


class AccountAuditStartThrottle(IPThrottle):
    scope = "growth_account_audit_start"
    rate = "60/minute"


class AccountAuditStartRequestSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField(help_text="Organization that owns the target team.")
    team_id = serializers.IntegerField(
        required=False,
        help_text="Target team ID. Defaults to the organization's oldest non-demo root project that is not pending deletion.",
        min_value=1,
    )
    reason = serializers.CharField(max_length=500, help_text="Why the account audit is being requested.")
    skill_name = serializers.CharField(
        max_length=64,
        default="onboarding-account-audit",
        help_text="Name of the single-file skill to load from project 2's skill store.",
    )


class AccountAuditStartResponseSerializer(serializers.Serializer):
    workflow_id = serializers.UUIDField(help_text="Started account audit workflow ID.")
    team_id = serializers.IntegerField(help_text="Resolved target team ID.")


class AccountAuditConflictSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why this audit did not start.")
    next_available_at = serializers.DateTimeField(required=False, help_text="Earliest next admission time.")


class AccountAuditStartViewSet(viewsets.ViewSet):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    scope_object = "INTERNAL"

    @extend_schema(
        request=AccountAuditStartRequestSerializer,
        responses={
            202: AccountAuditStartResponseSerializer,
            400: None,
            401: None,
            403: None,
            409: AccountAuditConflictSerializer,
            503: None,
        },
    )
    @action(methods=["POST"], detail=False, throttle_classes=[AccountAuditStartThrottle])
    def start(self, request: Request) -> Response:
        if request.content_type != "application/json":
            return Response(status=status.HTTP_400_BAD_REQUEST)
        try:
            if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_BODY_BYTES:
                return Response(status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        raw_body = request.body
        if len(raw_body) > MAX_BODY_BYTES:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        credential = self._credential(request)
        webhook_id = request.headers.get("webhook-id")
        timestamp = request.headers.get("webhook-timestamp")
        signature = request.headers.get("webhook-signature")
        if (
            credential is None
            or not webhook_id
            or len(webhook_id) > 255
            or not self._valid_signature(credential.signing_secret, webhook_id, timestamp, signature, raw_body)
        ):
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        payload = self._payload(raw_body)
        if payload is None:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        organization_id = payload.organization_id

        if not self._credential_is_eligible(credential):
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        team_id = self._resolve_team_id(payload)
        if team_id is None:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        if not self._ai_processing_is_approved(organization_id):
            return Response(status=status.HTTP_403_FORBIDDEN)

        actor_id = resolve_audit_actor_for_team(team_id)
        if actor_id is None:
            return Response(status=status.HTTP_403_FORBIDDEN)
        skill = get_skill_prompt(team_id=SOURCE_TEAM_ID, skill_name=payload.skill_name)
        if skill is None or not skill.body.strip():
            return Response(status=status.HTTP_400_BAD_REQUEST)

        admission, admission_status = self._admit(
            credential=credential,
            webhook_id=webhook_id,
            organization_id=organization_id,
            team_id=team_id,
            reason=payload.reason,
            skill_name=payload.skill_name,
        )
        if admission_status == "cooldown":
            return Response(
                {
                    "detail": "Wait seven days before starting another account audit.",
                    "next_available_at": (admission.created_at + COOLDOWN).isoformat(),
                },
                status=status.HTTP_409_CONFLICT,
            )
        if admission_status != "accepted":
            return Response({"detail": "This delivery ID has another audit request."}, status=status.HTTP_409_CONFLICT)

        try:
            async_to_sync(start_account_audit)(
                organization_id=str(organization_id),
                team_id=team_id,
                user_id=actor_id,
                workflow_id=str(admission.workflow_id),
                reason=admission.reason,
                skill_name=admission.skill_name,
            )
        except WorkflowAlreadyStartedError as error:
            if error.workflow_id != str(admission.workflow_id):
                logger.warning("account_audit_workflow_id_conflict", extra={"admission_id": admission.id})
                return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception:
            logger.exception("account_audit_workflow_dispatch_failed", extra={"admission_id": admission.id})
            return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(
            {"workflow_id": str(admission.workflow_id), "team_id": team_id}, status=status.HTTP_202_ACCEPTED
        )

    @staticmethod
    def _credential(request: Request) -> AccountAuditCredential | None:
        key_id = request.headers.get("X-PostHog-Audit-Key")
        try:
            return AccountAuditCredential.objects.select_related("owner").get(public_key_id=UUID(key_id or ""))
        except (AccountAuditCredential.DoesNotExist, TypeError, ValueError, AttributeError):
            return None

    @staticmethod
    def _valid_signature(
        signing_secret: str,
        webhook_id: str,
        timestamp: str | None,
        signature: str | None,
        raw_body: bytes,
    ) -> bool:
        if timestamp is None or signature is None:
            return False
        try:
            int(timestamp)
        except ValueError:
            return False
        version, separator, encoded_signature = signature.partition(",")
        if version != "v1" or not separator or not encoded_signature:
            return False
        secret = signing_secret.removeprefix("whsec_")
        try:
            signing_key = base64.b64decode(secret, validate=True)
            base64.b64decode(encoded_signature, validate=True)
        except (ValueError, binascii.Error):
            return False
        if len(signing_key) < 24:
            return False
        scheme = HmacSha256(
            secret_getter=lambda: signing_key,
            signature_header="webhook-signature",
            prefix="v1,",
            encoding="base64",
            signed_input="id_timestamp_body",
            delivery_id_header="webhook-id",
            timestamp_header="webhook-timestamp",
            timestamp_max_age_seconds=int(SIGNATURE_TOLERANCE.total_seconds()),
            timestamp_max_future_seconds=int(SIGNATURE_TOLERANCE.total_seconds()),
        )
        return (
            scheme.verify(
                body=raw_body,
                headers={"webhook-id": webhook_id, "webhook-timestamp": timestamp, "webhook-signature": signature},
            ).outcome
            == VerificationOutcome.VERIFIED
        )

    @staticmethod
    def _payload(raw_body: bytes) -> AccountAuditRequest | None:
        try:
            payload = json.loads(
                raw_body.decode("utf-8"), parse_constant=lambda _value: (_ for _ in ()).throw(ValueError)
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None
        if (
            not isinstance(payload, dict)
            or not {"organization_id", "reason"}.issubset(payload)
            or set(payload) - {"organization_id", "team_id", "reason", "skill_name"}
        ):
            return None
        try:
            organization_id = UUID(payload["organization_id"])
        except (TypeError, ValueError, AttributeError):
            return None
        team_id = payload.get("team_id")
        if "team_id" in payload and (isinstance(team_id, bool) or not isinstance(team_id, int) or team_id < 1):
            return None
        reason = payload["reason"]
        skill_name = payload.get("skill_name", "onboarding-account-audit")
        if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
            return None
        if not isinstance(skill_name, str) or not skill_name.strip() or len(skill_name.strip()) > 64:
            return None
        return AccountAuditRequest(
            organization_id=organization_id, team_id=team_id, reason=reason.strip(), skill_name=skill_name.strip()
        )

    @staticmethod
    def _resolve_team_id(request: AccountAuditRequest) -> int | None:
        teams = Team.objects.filter(organization_id=request.organization_id).exclude(project__is_pending_deletion=True)
        if request.team_id is not None:
            return teams.filter(id=request.team_id).values_list("id", flat=True).first()
        return (
            teams.filter(id=F("project_id"), parent_team__isnull=True, is_demo=False)
            .order_by("project__created_at", "id")
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
            and is_workflow_active_for_owner(
                workflow_id=credential.workflow_id,
                team_id=SOURCE_TEAM_ID,
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
            existing = AccountAuditAdmission.objects.filter(credential=credential, webhook_id=webhook_id).first()
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
                AccountAuditAdmission.objects.filter(
                    organization_id=organization_id, created_at__gt=timezone.now() - COOLDOWN
                )
                .order_by("-created_at")
                .first()
            )
            if recent is not None:
                return recent, "cooldown"
            admission = AccountAuditAdmission.objects.create(
                credential=credential,
                webhook_id=webhook_id,
                organization_id=organization_id,
                team_id=team_id,
                reason=reason,
                skill_name=skill_name,
            )
        return admission, "accepted"
