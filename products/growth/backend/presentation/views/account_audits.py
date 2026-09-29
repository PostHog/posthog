import base64
import binascii
from datetime import timedelta
from typing import Any
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.ingress.verify.schemes import HmacSha256, VerificationOutcome
from posthog.rate_limit import IPThrottle

from products.growth.backend.facade.account_audits import AccountAuditRequest, AccountAuditService

MAX_BODY_BYTES = 4 * 1024
SIGNATURE_TOLERANCE = timedelta(minutes=5)


class AccountAuditStartThrottle(IPThrottle):
    scope = "growth_account_audit_start"
    rate = "60/minute"


class AccountAuditStartRequestSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField(help_text="Organization that owns the target team.")
    team_id = serializers.IntegerField(
        required=False,
        help_text="Target team ID. Defaults to the non-demo root project with the most distinct resource viewers in the last 30 days, excluding projects pending deletion. Ties use the oldest project.",
        min_value=1,
    )
    reason = serializers.CharField(max_length=500, help_text="Why the account audit is being requested.")
    skill_name = serializers.CharField(
        max_length=64,
        default="onboarding-account-audit",
        help_text="Name of the single-file skill in the deployment's internal Growth project.",
    )

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        field_types = {"organization_id": str, "team_id": int, "reason": str, "skill_name": str}
        if not isinstance(data, dict) or set(data) - field_types.keys():
            raise serializers.ValidationError(
                {"non_field_errors": ["Expected an object containing only supported audit parameters."]}
            )
        if any(type(value) is not field_types[key] for key, value in data.items()):
            raise serializers.ValidationError({"non_field_errors": ["Audit parameters have invalid types."]})
        return super().to_internal_value(data)


class AccountAuditStartResponseSerializer(serializers.Serializer):
    task_run_id = serializers.UUIDField(help_text="Native task run executing the account audit.")
    team_id = serializers.IntegerField(help_text="Resolved target team ID.")


class AccountAuditConflictSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why this audit did not start.")
    next_available_at = serializers.DateTimeField(required=False, help_text="Earliest next admission time.")


class AccountAuditStartViewSet(viewsets.ViewSet):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]
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

        public_key_id = self._credential_key_id(request)
        signing_secret = AccountAuditService.signing_secret_for(public_key_id) if public_key_id else None
        webhook_id = request.headers.get("webhook-id")
        timestamp = request.headers.get("webhook-timestamp")
        signature = request.headers.get("webhook-signature")
        if (
            public_key_id is None
            or signing_secret is None
            or not webhook_id
            or len(webhook_id) > 255
            or not self._valid_signature(signing_secret, webhook_id, timestamp, signature, raw_body)
        ):
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        serializer = AccountAuditStartRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = AccountAuditRequest(**{"team_id": None, **serializer.validated_data})
        result = AccountAuditService.start(payload, public_key_id, webhook_id)
        if result.status == "accepted":
            return Response({"task_run_id": str(result.task_run_id), "team_id": result.team_id}, status=202)
        if result.status == "cooldown":
            return Response(
                {
                    "detail": "Wait seven days before starting another account audit.",
                    "next_available_at": result.next_available_at.isoformat() if result.next_available_at else None,
                },
                status=409,
            )
        if result.status == "conflict":
            return Response({"detail": "This delivery ID has another audit request."}, status=409)
        return Response(
            status={"invalid": 400, "unauthorized": 401, "forbidden": 403, "unavailable": 503}[result.status]
        )

    @staticmethod
    def _credential_key_id(request: Request) -> UUID | None:
        key_id = request.headers.get("X-PostHog-Audit-Key")
        try:
            return UUID(key_id or "")
        except (TypeError, ValueError, AttributeError):
            return None

    @staticmethod
    def _valid_signature(
        signing_secret: str,
        webhook_id: str,
        timestamp: str | None,
        signature: str | None,
        raw_body: bytes,
    ) -> bool:
        secret = signing_secret.removeprefix("whsec_")
        try:
            signing_key = base64.b64decode(secret, validate=True)
        except (ValueError, binascii.Error):
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
                headers={
                    "webhook-id": webhook_id,
                    "webhook-timestamp": timestamp or "",
                    "webhook-signature": signature or "",
                },
            ).outcome
            == VerificationOutcome.VERIFIED
        )
