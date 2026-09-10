from __future__ import annotations

from dataclasses import asdict

from django.conf import settings

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.oauth_provenance import get_oauth_access_token
from posthog.permissions import APIScopePermission
from posthog.temporal.oauth import PULSE_RESEARCH_INTERNAL_SCOPE

from products.subscriptions.backend.facade.api import run_public_research
from products.subscriptions.backend.facade.contracts import PublicResearchResult
from products.subscriptions.backend.presentation.serializers import (
    PulseResearchRequestSerializer,
    PulseResearchResponseSerializer,
)


@extend_schema(tags=["subscriptions"])
class PulseResearchViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Server-only public-web research for a Pulse analysis run."""

    permission_classes = [APIScopePermission]
    scope_object = "INTERNAL"

    def dangerously_get_required_scopes(self, request: Request, view=None) -> list[str] | None:  # noqa: ANN001
        return [PULSE_RESEARCH_INTERNAL_SCOPE]

    @extend_schema(request=PulseResearchRequestSerializer, responses={200: PulseResearchResponseSerializer})
    @action(detail=False, methods=["POST"], required_scopes=[PULSE_RESEARCH_INTERNAL_SCOPE])
    def search(self, request: Request, team_id: int) -> Response:
        if not settings.PULSE_PROACTIVE_ENABLED or not settings.PULSE_PUBLIC_RESEARCH_ENABLED:
            raise PermissionDenied("Pulse public research is disabled.")

        access_token = get_oauth_access_token(request)
        scopes = set((getattr(access_token, "scope", "") or "").split())
        if PULSE_RESEARCH_INTERNAL_SCOPE not in scopes or getattr(access_token, "sandbox_task_id", None) is None:
            raise PermissionDenied("Pulse public research is available only to its staged analysis run.")

        serializer = PulseResearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = run_public_research(serializer.validated_data["query"])
        return Response(PulseResearchResponseSerializer(_response_payload(result)).data, status=status.HTTP_200_OK)


def _response_payload(result: PublicResearchResult) -> dict[str, object]:
    return {"citations": [asdict(citation) for citation in result.citations], "degradation": result.degradation}
