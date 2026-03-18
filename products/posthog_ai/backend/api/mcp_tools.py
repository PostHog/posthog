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
        if self.action == "invoke_tool":
            tool_name = self.kwargs.get("tool_name", "")
            scopes = mcp_tool_registry.get_scopes(tool_name)
            return scopes or None
        return None

    @action(
        detail=False,
        methods=["POST"],
        url_path="(?P<tool_name>[^/.]+)",
    )
    def invoke_tool(self, request: Request, tool_name: str, *args, **kwargs):
        """
        Invoke an MCP tool by name.

        This endpoint allows MCP callers to invoke Max AI tools directly
        without going through the full LangChain conversation flow.

        Scopes are resolved dynamically per tool via dangerously_get_required_scopes.
        """
        tool = mcp_tool_registry.get(tool_name, team=self.team, user=cast(User, request.user))
        if tool is None:
            return Response(
                {"success": False, "content": f"Tool '{tool_name}' not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        args_data = request.data.get("args", {})

        try:
            validated_args = tool.args_schema.model_validate(args_data)
        except pydantic.ValidationError as e:
            return Response(
                {
                    "success": False,
                    "content": f"There was a validation error calling the tool:\n{e.errors(include_url=False)}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            content = async_to_sync(tool.execute)(validated_args)
        except MaxToolError as e:
            return Response({"success": False, "content": f"Tool failed: {e.to_summary()}.{e.retry_hint}"})
        except Exception as e:
            logger.exception("Error calling tool", extra={"tool_name": tool_name, "error": str(e)})
            capture_exception(e, properties={"tag": "mcp", "args": args_data})
            return Response(
                {
                    "success": False,
                    "content": "The tool raised an internal error. Do not immediately retry the tool call.",
                }
            )

        return Response({"success": True, "content": content})
