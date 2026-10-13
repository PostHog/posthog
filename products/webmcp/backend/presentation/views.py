"""
DRF views for webmcp.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from typing import cast

from drf_spectacular.utils import OpenApiResponse
from loginas.utils import is_impersonated_session
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from ..facade import api, contracts
from .serializers import WebMCPExecRequestSerializer, WebMCPExecResultSerializer, WebMCPExecToolSerializer


class McpServerUnavailable(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The PostHog MCP server could not complete the request."
    default_code = "mcp_server_unavailable"


class WebMCPViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    # Session only: WebMCP exists for the logged-in browser, and a token caller can reach the MCP directly.
    scope_object = "INTERNAL"

    def _check_not_impersonating(self, request: Request) -> None:
        # A minted token would carry the impersonated user's access past the read-only session rules.
        if is_impersonated_session(request):
            raise PermissionDenied("WebMCP is not available in an impersonated session.")

    @validated_request(
        responses={200: OpenApiResponse(response=WebMCPExecToolSerializer)},
        summary="Get the exec tool definition to register with WebMCP",
    )
    @action(detail=False, methods=["get"], url_path="tool")
    def tool(self, request: Request, **kwargs) -> Response:
        self._check_not_impersonating(request)
        try:
            tool = api.get_exec_tool(cast(User, request.user).id, self.team_id)
        except contracts.McpServerError as error:
            raise McpServerUnavailable(str(error)) from error
        return Response(WebMCPExecToolSerializer(tool).data)

    @validated_request(
        request_serializer=WebMCPExecRequestSerializer,
        responses={200: OpenApiResponse(response=WebMCPExecResultSerializer)},
        summary="Run an exec command on the PostHog MCP server",
    )
    @action(detail=False, methods=["post"], url_path="exec")
    def exec(self, request: Request, **kwargs) -> Response:
        self._check_not_impersonating(request)
        try:
            result = api.run_exec(
                contracts.RunExecInput(
                    user_id=cast(User, request.user).id,
                    team_id=self.team_id,
                    command=request.validated_data["command"],
                )
            )
        except contracts.McpServerError as error:
            raise McpServerUnavailable(str(error)) from error
        return Response(WebMCPExecResultSerializer(result).data)
