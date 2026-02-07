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
    renderer_classes = [SafeJSONRenderer]

    def list(self, request: Request, *args, **kwargs) -> Response:
        tools = mcp_tool_registry.get_all_tools()
        return Response({"tools": [tool.model_dump() for tool in tools]})

    @action(methods=["POST"], detail=False)
    def run(self, request: Request, *args, **kwargs) -> Response:
        tool_name = request.data.get("tool_name")
        args_data = request.data.get("args", {})

        if not tool_name:
            return Response({"success": False, "content": "Tool name is required."}, status=status.HTTP_400_BAD_REQUEST)

        user = cast(User, request.user)
        try:
            tool = mcp_tool_registry.get_tool(tool_name)
            if not tool:
                 return Response({"success": False, "content": f"Tool {tool_name} not found."}, status=status.HTTP_404_NOT_FOUND)

            content = async_to_sync(tool.run)(args=args_data, context={"team_id": self.team_id, "user": user})
        except pydantic.ValidationError as e:
            return Response({"success": False, "content": f"Invalid arguments: {e}"}, status=status.HTTP_400_BAD_REQUEST)
        except MaxToolError as e:
            return Response({"success": False, "content": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Error calling tool", extra={"tool_name": tool_name, "error": str(e)})
            capture_exception(e, properties={"tag": "mcp", "args": args_data})
            return Response({"success": False, "content": "Internal error. Do not retry."})

        return Response({"success": True, "content": content})