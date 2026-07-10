"""Aggregated MCP gateway endpoints.

One team-scoped access point over every connected MCP server installation,
consumed by the PostHog MCP (``services/mcp``):

- ``GET .../mcp_gateway/tools/`` — REST tool catalog (search / exact name /
  pagination).
- ``POST .../mcp_gateway/call/`` — REST tool execution with typed error mapping.
"""

from typing import Any, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.rate_limit import MCPProxyBurstThrottle, MCPProxySustainedThrottle

from ..analytics import MCP_CONSUMER_HEADER
from ..gateway import (
    GatewayToolBlockedError,
    GatewayToolNeedsApprovalError,
    GatewayToolNotFoundError,
    GatewayUpstreamError,
    call_gateway_tool,
    list_gateway_tools,
)
from ..models import APPROVAL_STATES, SCOPE_CHOICES


@extend_schema_field(OpenApiTypes.OBJECT)
class JSONObjectField(serializers.JSONField):
    """A JSON object with server-defined structure (typed as a generic object downstream)."""


class GatewayServerSerializer(serializers.Serializer):
    slug = serializers.CharField(help_text="URL-safe server identifier, unique within the caller's resolved set.")
    display_name = serializers.CharField(help_text="Human-readable server name.")
    installation_id = serializers.CharField(help_text="UUID of the MCP server installation backing this server.")
    scope = serializers.ChoiceField(
        choices=SCOPE_CHOICES, help_text="'personal' is the caller's own installation; 'shared' is team-wide."
    )


class GatewayToolSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Namespaced tool name: {server_slug}/{tool_name}.")
    server = GatewayServerSerializer(help_text="The connected server this tool belongs to.")
    tool_name = serializers.CharField(help_text="The tool's name on the upstream server (not namespaced).")
    description = serializers.CharField(allow_blank=True, help_text="Tool description from the upstream server.")
    input_schema = JSONObjectField(help_text="JSON Schema describing the tool's arguments.")
    approval_state = serializers.ChoiceField(
        choices=APPROVAL_STATES,
        help_text="Per-tool approval state. 'needs_approval' tools are listed but blocked at call time.",
    )


class GatewayToolsQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False, help_text="Substring search over tool name and description; name matches rank first."
    )
    name = serializers.CharField(required=False, help_text="Exact namespaced tool name ({server_slug}/{tool_name}).")
    limit = serializers.IntegerField(
        required=False, default=100, min_value=1, max_value=500, help_text="Maximum number of tools to return."
    )
    offset = serializers.IntegerField(
        required=False, default=0, min_value=0, help_text="Number of tools to skip (for pagination)."
    )


class GatewayToolsResponseSerializer(serializers.Serializer):
    results = GatewayToolSerializer(many=True, help_text="The page of matching tools.")
    count = serializers.IntegerField(help_text="Total number of matching tools before pagination.")


class GatewayCallRequestSerializer(serializers.Serializer):
    tool = serializers.CharField(help_text="Namespaced tool name to execute: {server_slug}/{tool_name}.")
    arguments = serializers.DictField(
        child=serializers.JSONField(),
        required=False,
        default=dict,
        help_text="Arguments passed to the tool, matching its input_schema.",
    )
    consumer = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional consumer identifier for analytics attribution (e.g. 'tasks', 'max').",
    )


class GatewayCallResponseSerializer(serializers.Serializer):
    content = serializers.ListField(
        child=JSONObjectField(), help_text="MCP CallToolResult content blocks (e.g. {type: 'text', text: ...})."
    )
    is_error = serializers.BooleanField(help_text="True when the tool itself reported an execution error.")
    structured_content = JSONObjectField(
        required=False, allow_null=True, help_text="Structured result payload, when the tool provides one."
    )
    server_slug = serializers.CharField(help_text="Slug of the server that executed the tool.")
    tool_name = serializers.CharField(help_text="The tool's name on the upstream server (not namespaced).")
    duration_ms = serializers.IntegerField(help_text="Upstream execution time in milliseconds.")


class GatewayCallErrorSerializer(serializers.Serializer):
    code = serializers.ChoiceField(
        choices=["tool_not_found", "tool_needs_approval", "tool_blocked", "upstream_error"],
        help_text="Machine-readable error code.",
    )
    detail = serializers.CharField(help_text="Human-readable error description.")
    approval_url = serializers.CharField(
        required=False, help_text="Settings URL where the tool can be approved (tool_needs_approval only)."
    )
    error_type = serializers.CharField(
        required=False,
        help_text="Upstream failure category (upstream_error only): e.g. unreachable, timeout, auth_failed.",
    )


class MCPGatewayViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Aggregated MCP gateway over all of a team's connected MCP server installations.

    Resolution is per caller: shared installations plus the caller's personal
    ones, with a personal installation shadowing a shared one for the same URL.
    Tool names are namespaced as ``{server_slug}/{tool_name}``.
    """

    scope_object = "project"
    permission_classes = [IsAuthenticated]

    @validated_request(
        query_serializer=GatewayToolsQuerySerializer,
        responses={200: OpenApiResponse(response=GatewayToolsResponseSerializer)},
        summary="List gateway tools",
        description="The merged, namespaced tool catalog across the caller's connected MCP servers.",
    )
    @action(detail=False, methods=["get"], url_path="tools", required_scopes=["project:read"])
    def tools(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        query = request.validated_query_data
        infos = list_gateway_tools(
            self.team_id,
            cast(User, request.user).id,
            search=query.get("search"),
            name=query.get("name"),
        )
        offset = query.get("offset", 0)
        limit = query.get("limit", 100)
        page = infos[offset : offset + limit]
        return Response({"results": GatewayToolSerializer(page, many=True).data, "count": len(infos)})

    @validated_request(
        GatewayCallRequestSerializer,
        responses={
            200: OpenApiResponse(response=GatewayCallResponseSerializer),
            403: OpenApiResponse(response=GatewayCallErrorSerializer),
            404: OpenApiResponse(response=GatewayCallErrorSerializer),
            502: OpenApiResponse(response=GatewayCallErrorSerializer),
        },
        summary="Call a gateway tool",
        description="Execute a namespaced tool ({server_slug}/{tool_name}) on the connected server that owns it.",
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="call",
        throttle_classes=[MCPProxyBurstThrottle, MCPProxySustainedThrottle],
        required_scopes=["project:read"],
    )
    def call(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        data = request.validated_data
        consumer = data.get("consumer") or request.headers.get(MCP_CONSUMER_HEADER) or None

        try:
            result = call_gateway_tool(
                team=self.team,
                user=cast(User, request.user),
                tool=data["tool"],
                arguments=data.get("arguments") or {},
                consumer=consumer,
            )
        except GatewayToolNotFoundError as exc:
            return Response({"code": "tool_not_found", "detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except GatewayToolNeedsApprovalError as exc:
            return Response(
                {"code": "tool_needs_approval", "detail": str(exc), "approval_url": exc.approval_url},
                status=status.HTTP_403_FORBIDDEN,
            )
        except GatewayToolBlockedError as exc:
            return Response({"code": "tool_blocked", "detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except GatewayUpstreamError as exc:
            return Response(
                {"code": "upstream_error", "detail": str(exc), "error_type": exc.error_type},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(GatewayCallResponseSerializer(result).data)
