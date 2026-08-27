from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models import User
from posthog.permissions import APIScopePermission

from products.tasks.backend.facade.access import DesktopAccessResolutionError, get_desktop_access_decision
from products.tasks.backend.presentation.serializers import (
    DesktopAccessResponseSerializer,
    TaskRunErrorResponseSerializer,
)


@extend_schema(tags=["tasks"])
class DesktopAccessViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    pagination_class = None
    serializer_class = DesktopAccessResponseSerializer

    @extend_schema(
        responses={
            200: OpenApiResponse(response=DesktopAccessResponseSerializer),
            503: OpenApiResponse(response=TaskRunErrorResponseSerializer),
        },
        summary="Check PostHog Desktop access",
        description="Evaluate Desktop access for the selected project and organization.",
    )
    @action(detail=False, methods=["get"], url_path="access", required_scopes=["llm_gateway:read"])
    def access(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            decision = get_desktop_access_decision(cast(User, request.user), self.organization)
        except DesktopAccessResolutionError:
            return Response(
                TaskRunErrorResponseSerializer(
                    {
                        "type": "service_unavailable",
                        "code": "desktop_access_unavailable",
                        "error": "We couldn't verify PostHog Desktop access. Try again.",
                    }
                ).data,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            DesktopAccessResponseSerializer(
                {
                    "allowed": decision.allowed,
                    "reason": decision.reason.value if decision.reason is not None else None,
                }
            ).data
        )
