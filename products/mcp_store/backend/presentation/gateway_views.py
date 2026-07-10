"""Aggregated MCP gateway endpoints.

One team-scoped access point over every connected MCP server installation:

- ``POST .../mcp_gateway/mcp/`` — stateless JSON-RPC (MCP streamable HTTP) for
  external agents: initialize, notifications/initialized, ping, tools/list,
  tools/call.
- ``GET .../mcp_gateway/tools/`` — REST tool catalog (search / exact name /
  pagination) for the Hono MCP front door and internal consumers.
- ``POST .../mcp_gateway/call/`` — REST tool execution with typed error mapping.
"""

import json
import uuid
from typing import Any, cast

from django.http import HttpResponse

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.rate_limit import MCPProxyBurstThrottle, MCPProxySustainedThrottle

from ..analytics import MCP_CONSUMER_HEADER
from ..facade.contracts import (
    GatewayToolBlockedError,
    GatewayToolNeedsApprovalError,
    GatewayToolNotFoundError,
    GatewayUpstreamError,
)
from ..gateway import call_gateway_tool, list_gateway_tools
from ..models import APPROVAL_STATES, SCOPE_CHOICES
from ..proxy import BATCH_REJECTED_CODE, METHOD_NOT_FOUND_CODE, TOOL_DISABLED_CODE, TOOL_NEEDS_APPROVAL_CODE
from ..tools import _PROTOCOL_VERSION
from .views import MCPProxyRenderer

logger = structlog.get_logger(__name__)

# JSON-RPC implementation-defined server error, used for upstream failures.
SERVER_ERROR_CODE = -32000

_SERVER_INFO = {"name": "posthog-mcp-gateway", "version": "1.0"}


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


def _jsonrpc_error_dict(request_id: Any, code: int, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _json_response(payload: dict[str, Any] | list[Any], http_status: int = 200) -> HttpResponse:
    return HttpResponse(json.dumps(payload), content_type="application/json", status=http_status)


def _jsonrpc_result_response(request_id: Any, result: dict[str, Any]) -> HttpResponse:
    return _json_response({"jsonrpc": "2.0", "id": request_id, "result": result})


def _jsonrpc_error_response(
    request_id: Any, code: int, message: str, data: dict[str, Any] | None = None
) -> HttpResponse:
    return _json_response(_jsonrpc_error_dict(request_id, code, message, data))


class MCPGatewayViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Aggregated MCP gateway over all of a team's connected MCP server installations.

    Resolution is per caller: shared installations plus the caller's personal
    ones, with a personal installation shadowing a shared one for the same URL.
    Tool names are namespaced as ``{server_slug}/{tool_name}``.
    """

    scope_object = "project"
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Aggregated MCP endpoint",
        description=(
            "Stateless JSON-RPC (MCP streamable HTTP) over the caller's connected MCP servers. "
            "Supports initialize, notifications/initialized, ping, tools/list, and tools/call "
            "with {server_slug}/{tool_name} tool names. Batch requests are rejected."
        ),
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="mcp",
        throttle_classes=[MCPProxyBurstThrottle, MCPProxySustainedThrottle],
        required_scopes=["project:read"],
        renderer_classes=[MCPProxyRenderer],
    )
    def mcp(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        data = request.data
        if isinstance(data, list):
            return _json_response(
                [
                    _jsonrpc_error_dict(
                        (item.get("id") if isinstance(item, dict) else None),
                        BATCH_REJECTED_CODE,
                        "Batch requests are not supported by the MCP gateway; send items individually",
                    )
                    for item in data
                ]
            )
        if not isinstance(data, dict):
            return HttpResponse(
                '{"error": "Request body must be valid JSON"}',
                content_type="application/json",
                status=400,
            )

        method = data.get("method")
        rpc_id = data.get("id")

        if method == "initialize":
            params = data.get("params")
            requested_version = params.get("protocolVersion") if isinstance(params, dict) else None
            protocol_version = (
                requested_version if isinstance(requested_version, str) and requested_version else _PROTOCOL_VERSION
            )
            response = _jsonrpc_result_response(
                rpc_id,
                {
                    "protocolVersion": protocol_version,
                    "capabilities": {"tools": {}},
                    "serverInfo": _SERVER_INFO,
                },
            )
            # The gateway is stateless; mint an id for clients that require one
            # and accept any value on subsequent requests.
            response["Mcp-Session-Id"] = uuid.uuid4().hex
            return response

        if method == "notifications/initialized":
            return HttpResponse(status=202)

        if method == "ping":
            return _jsonrpc_result_response(rpc_id, {})

        if method == "tools/list":
            infos = list_gateway_tools(self.team_id, cast(User, request.user).id)
            return _jsonrpc_result_response(
                rpc_id,
                {
                    "tools": [
                        {"name": info.name, "description": info.description, "inputSchema": info.input_schema}
                        for info in infos
                    ]
                },
            )

        if method == "tools/call":
            return self._handle_tools_call(request, data)

        return _jsonrpc_error_response(rpc_id, METHOD_NOT_FOUND_CODE, f"Method '{method}' not found")

    def _handle_tools_call(self, request: Request, data: dict[str, Any]) -> HttpResponse:
        rpc_id = data.get("id")
        params = data.get("params")
        tool_name = params.get("name") if isinstance(params, dict) else None
        if not tool_name or not isinstance(tool_name, str):
            return _jsonrpc_error_response(rpc_id, METHOD_NOT_FOUND_CODE, "tools/call missing 'name' parameter")

        raw_arguments = params.get("arguments") if isinstance(params, dict) else None
        arguments = raw_arguments if isinstance(raw_arguments, dict) else {}

        try:
            result = call_gateway_tool(
                team=self.team,
                user=cast(User, request.user),
                tool=tool_name,
                arguments=arguments,
                consumer=request.headers.get(MCP_CONSUMER_HEADER),
            )
        except GatewayToolNotFoundError as exc:
            return _jsonrpc_error_response(rpc_id, METHOD_NOT_FOUND_CODE, str(exc))
        except GatewayToolNeedsApprovalError as exc:
            return _jsonrpc_error_response(
                rpc_id, TOOL_NEEDS_APPROVAL_CODE, str(exc), data={"approval_url": exc.approval_url}
            )
        except GatewayToolBlockedError as exc:
            return _jsonrpc_error_response(rpc_id, TOOL_DISABLED_CODE, str(exc))
        except GatewayUpstreamError as exc:
            return _jsonrpc_error_response(rpc_id, SERVER_ERROR_CODE, str(exc), data={"error_type": exc.error_type})

        payload: dict[str, Any] = {"content": result.content, "isError": result.is_error}
        if result.structured_content is not None:
            payload["structuredContent"] = result.structured_content
        return _jsonrpc_result_response(rpc_id, payload)

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
