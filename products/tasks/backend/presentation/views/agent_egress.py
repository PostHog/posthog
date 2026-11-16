from collections.abc import Mapping
from datetime import timedelta
from typing import cast
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.auth import ScopedServiceJWTAuthentication
from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

from products.tasks.backend.facade import api as tasks_facade

AGENT_EGRESS_REGISTRY_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.AGENT_EGRESS_REGISTRY,
    settings_name="AGENT_EGRESS_REGISTRY_JWT_SECRETS",
    default_ttl=timedelta(seconds=30),
)


class AgentEgressRegistryAuthentication(ScopedServiceJWTAuthentication):
    purpose = AGENT_EGRESS_REGISTRY_PURPOSE


class AgentEgressRegistrationSerializer(serializers.Serializer):
    run_id = serializers.UUIDField(help_text="Run bound to this registration.")
    team_id = serializers.IntegerField(help_text="Project that owns the run.")
    execution_id = serializers.UUIDField(help_text="Execution bound to the relay key.")
    actor_id = serializers.IntegerField(help_text="Actor whose authority the run uses.")
    actor_epoch = serializers.IntegerField(help_text="Version of the actor's authority.")
    relay_key_sha256 = serializers.CharField(help_text="Unpadded base64url SHA-256 fingerprint of the relay SPKI.")
    authority = serializers.CharField(help_text="Exact run hostname and optional port.")
    region = serializers.CharField(help_text="Region where the registration is valid.")
    lease_expires_at = serializers.DateTimeField(help_text="Absolute deadline for cached authorization.")
    revoked = serializers.BooleanField(help_text="Whether the execution has been revoked.")


class AgentEgressRegistrationView(APIView):
    authentication_classes = [AgentEgressRegistryAuthentication]
    permission_classes = [IsAuthenticated]
    http_method_names = ["get"]

    @extend_schema(exclude=True, responses={200: AgentEgressRegistrationSerializer})
    def get(self, request: Request, team_id: int, run_id: UUID, execution_id: UUID) -> Response:
        region = settings.AGENT_EGRESS_REGION
        if not region:
            return Response({"detail": "Registration unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        claims = cast(Mapping[str, object], request.auth)
        issued_at, expires_at = claims.get("iat"), claims.get("exp")
        if (
            type(issued_at) is not int
            or type(expires_at) is not int
            or not 0 < expires_at - issued_at <= 30
            or claims.get("aud") != AGENT_EGRESS_REGISTRY_PURPOSE.audience.value
            or claims.get("sub") != str(run_id)
            or claims.get("execution_id") != str(execution_id)
            or claims.get("operation") != "lookup"
            or claims.get("region") != region
        ):
            return Response({"detail": "Registration access denied."}, status=status.HTTP_403_FORBIDDEN)

        try:
            registration = tasks_facade.get_agent_egress_registration(
                team_id=team_id, run_id=run_id, execution_id=execution_id, region=region
            )
        except ImproperlyConfigured:
            return Response({"detail": "Registration unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if registration is None:
            return Response({"detail": "Registration not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AgentEgressRegistrationSerializer(registration).data, headers={"Cache-Control": "no-store"})
