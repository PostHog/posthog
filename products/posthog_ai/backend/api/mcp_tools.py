from typing import cast

from django.views.generic import View

import pydantic
from asgiref.sync import async_to_sync
from posthoganalytics import capture_exception
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from structlog import get_logger

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.renderers import SafeJSONRenderer

from ee.hogai.mcp_tool import mcp_tool_registry
from ee.hogai.tool_errors import MaxToolError

logger = get_logger(__name__)


class MCPToolsViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "project"
    renderer_classes = [SafeJSONRenderer]

    def dangerously_get_required_scopes(self, request: Request, view: View) -> list[str] | None:
        if self.action == "run":
            tool_name = request.data.get("tool_name")
            if tool_name:
                return mcp_tool_registry.get_scopes(tool_name)
        return None

    def list(self, request: Request, *args, **kwargs) -> Response:
        """
        List all available MCP tools.
        """
        user = cast(User, request.user)
        tools = []
        for name in mcp_tool_registry.get_names():
            tool = mcp_tool_registry.get(name, team=self.team, user=user)
            if tool:
                tools.append(tool.model_dump())
        return Response({"tools": tools})

    @action(methods=["POST"], detail=False)
    def run(self, request: Request, *args, **kwargs) -> Response:
        """
        Execute a specific MCP tool.
        Expects tool_name and args in the request body.
        """
        tool_name = request.data.get("tool_name")
        args_data = request.data.get("args", {})

        if not tool_name:
            return Response(
                {"success": False, "content": "Tool name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = cast(User, request.user)
        tool = mcp_tool_registry.get(tool_name, team=self.team, user=user)

        if not tool:
            return Response(
                {"success": False, "content": f"Tool {tool_name} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            validated_args = tool.args_schema.model_validate(args_data)
            content = async_to_sync(tool.execute)(validated_args)

        except pydantic.ValidationError as e:
            return Response(
                {"success": False, "content": f"Invalid arguments: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except MaxToolError as e:
            return Response(
                {"success": False, "content": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.exception("Error calling tool", extra={"tool_name": tool_name, "error": str(e)})
            capture_exception(e, properties={"tag": "mcp", "args": args_data})
            return Response(
                {
                    "success": False,
                    "content": "The tool raised an internal error. Do not immediately retry the tool call.",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"success": True, "content": content})
