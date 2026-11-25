import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import cast
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import Throttled
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from posthog.auth import ScopedServiceJWTAuthentication
from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose
from posthog.token_bucket import BucketUnavailable, Budget, consume

from products.tasks.backend.facade import egress
from products.tasks.backend.presentation.views.agent_egress import AgentEgressRegistrationSerializer

logger = logging.getLogger(__name__)
GIT_GRANT_LOOKUP_BUDGET = Budget(burst=60, per_hour=600)

AGENT_EGRESS_CREDENTIALS_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.AGENT_EGRESS_CREDENTIALS,
    settings_name="AGENT_EGRESS_CREDENTIALS_JWT_SECRETS",
    default_ttl=timedelta(seconds=30),
)


class AgentEgressCredentialsAuthentication(ScopedServiceJWTAuthentication):
    purpose = AGENT_EGRESS_CREDENTIALS_PURPOSE


class GitReadGrantSerializer(serializers.Serializer):
    registration = AgentEgressRegistrationSerializer(help_text="Current execution authority.")
    repository = serializers.CharField(help_text="Exact owner/repository granted Git read access.")
    credential_version = serializers.UUIDField(help_text="Opaque version of the published credential.")
    expires_at = serializers.DateTimeField(help_text="Absolute credential validity deadline.")
    token = serializers.CharField(help_text="Upstream credential for the authenticated egress service only.")


class AgentEgressGitGrantViewSet(ViewSet):
    authentication_classes = [AgentEgressCredentialsAuthentication]
    permission_classes = [IsAuthenticated]
    http_method_names = ["get"]

    def finalize_response(self, request: Request, response: Response, *args: object, **kwargs: object) -> Response:
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    @extend_schema(exclude=True, responses={200: GitReadGrantSerializer})
    def list(self, request: Request, parent_lookup_team_id: str, run_id: str, execution_id: str) -> Response:
        if not request.is_secure() or not settings.AGENT_EGRESS_REGION:
            return Response({"detail": "Git grant unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        claims = cast(Mapping[str, object], request.auth)
        issued_at, expires_at = claims.get("iat"), claims.get("exp")
        repository = claims.get("repository")
        if (
            type(issued_at) is not int
            or type(expires_at) is not int
            or not 0 < expires_at - issued_at <= 30
            or claims.get("aud") != AGENT_EGRESS_CREDENTIALS_PURPOSE.audience.value
            or claims.get("sub") != run_id
            or claims.get("execution_id") != execution_id
            or claims.get("region") != settings.AGENT_EGRESS_REGION
            or claims.get("operation") != "git_read_grant"
            or not isinstance(repository, str)
        ):
            return Response({"detail": "Git grant access denied."}, status=status.HTTP_403_FORBIDDEN)
        decision = consume(
            f"agent_egress_git_grant:{int(parent_lookup_team_id)}:{UUID(execution_id)}", GIT_GRANT_LOOKUP_BUDGET
        )
        if isinstance(decision, BucketUnavailable):
            logger.warning(
                "agent_egress_git_grant_rate_limit_unavailable",
                extra={"team_id": int(parent_lookup_team_id), "execution_id": execution_id},
            )
            return Response({"detail": "Git grant unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not decision.allowed:
            raise Throttled(wait=decision.retry_after)
        try:
            grant = egress.get_git_read_grant(
                team_id=int(parent_lookup_team_id),
                run_id=UUID(run_id),
                execution_id=UUID(execution_id),
                region=settings.AGENT_EGRESS_REGION,
                repository=repository,
            )
        except (ImproperlyConfigured, DatabaseError, egress.GitGrantUnavailable) as error:
            logger.warning(
                "agent_egress_git_grant_unavailable",
                extra={
                    "error_type": type(error).__name__,
                    "team_id": int(parent_lookup_team_id),
                    "run_id": run_id,
                    "execution_id": execution_id,
                },
            )
            return Response({"detail": "Git grant unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if grant is None:
            return Response({"detail": "Git grant not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(GitReadGrantSerializer(grant).data)
