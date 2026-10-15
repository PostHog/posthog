import json
from typing import cast
from uuid import uuid4

from django.conf import settings
from django.views.generic import View

import pydantic
from asgiref.sync import async_to_sync
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from openai import AsyncOpenAI
from posthoganalytics import capture_exception
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from structlog import get_logger

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tags_context
from posthog.event_usage import get_event_source
from posthog.exceptions_capture import exception_context
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.renderers import SafeJSONRenderer
from posthog.storage.object_storage import ObjectStorageError

from products.posthog_ai.backend.mcp_result_files import (
    MCP_RESULT_FILE_MAX_BYTES,
    MCP_RESULT_FILE_URL_TTL_SECONDS,
    MCPResultFiles,
)

from ee.hogai.mcp_tool import MCPToolResult, mcp_tool_registry
from ee.hogai.tool_errors import MaxToolError, MaxToolErrorType
from ee.hogai.tools.docs_search_shadow import fetch_inkeep_with_shadow
from ee.hogai.tools.search import format_inkeep_docs_response

logger = get_logger(__name__)


class MCPToolRequest(pydantic.BaseModel):
    args: dict[str, pydantic.JsonValue] = pydantic.Field(
        default_factory=dict, description="Arguments validated against the selected tool's schema."
    )


class MCPToolResponse(MCPToolResult):
    success: bool = pydantic.Field(description="Whether the tool completed successfully.")
    error_type: MaxToolErrorType | None = pydantic.Field(
        default=None, description="Failure category for MCP analytics."
    )
    error_code: str | None = pydantic.Field(
        default=None,
        description="Machine-readable name of the leaf failure for MCP analytics, such as a ClickHouse error name.",
    )


class DocsSearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(
        help_text=(
            "Natural-language description of what to find in the PostHog documentation. "
            "Inkeep performs hybrid (semantic + full-text) RAG, so phrase the query the way "
            "a user would ask the question."
        )
    )


class DocsSearchResponseSerializer(serializers.Serializer):
    content = serializers.CharField(
        help_text=(
            "Markdown-formatted documentation results. Each block has a title, URL and excerpt; "
            "an empty result set returns guidance to navigate to https://posthog.com/docs."
        )
    )


class _DocsSearchUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Documentation search is not available: INKEEP_API_KEY is not configured."
    default_code = "docs_search_unavailable"


class MCPStoredResultRequestSerializer(serializers.Serializer):
    content = serializers.CharField(
        max_length=MCP_RESULT_FILE_MAX_BYTES,
        trim_whitespace=False,
        help_text="Complete MCP tool response serialized as JSON, limited to 8 MiB of UTF-8 text.",
    )

    def validate_content(self, value: str) -> str:
        if len(value.encode("utf-8")) > MCP_RESULT_FILE_MAX_BYTES:
            raise serializers.ValidationError("The result exceeds the 8 MiB file limit.")
        try:
            json.loads(value)
        except (ValueError, RecursionError):
            raise serializers.ValidationError("The result must contain valid JSON.")
        return value


class MCPStoredResultResponseSerializer(serializers.Serializer):
    download_url = serializers.URLField(help_text="Presigned URL for downloading the complete MCP response as JSON.")
    expires_in = serializers.IntegerField(help_text="Number of seconds until the download URL expires.")


class _MCPResultFileUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Result file storage is unavailable. Use the original inline response."
    default_code = "mcp_result_file_unavailable"


class MCPToolsViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "project"
    serializer_class = _FallbackSerializer
    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = {"mcp-openai-result-files": ["store_result"]}

    renderer_classes = [SafeJSONRenderer]

    def dangerously_get_required_scopes(self, request: Request, view: View) -> list[str] | None:
        if self.action == "invoke_tool":
            tool_name = self.kwargs.get("tool_name", "")
            scopes = mcp_tool_registry.get_scopes(tool_name)
            return scopes or None
        return None

    @validated_request(
        request_serializer=MCPStoredResultRequestSerializer,
        responses={200: MCPStoredResultResponseSerializer},
        extensions={"x-internal": True},
    )
    @action(detail=False, methods=["POST"], url_path="results/store", required_scopes=["project:read"])
    def store_result(self, request: ValidatedRequest, **kwargs: object) -> Response:
        if not settings.OBJECT_STORAGE_ENABLED:
            raise _MCPResultFileUnavailable()
        content = cast(str, request.validated_data["content"])
        try:
            url = MCPResultFiles.store(team_id=self.team.id, content=content)
        except ObjectStorageError:
            raise _MCPResultFileUnavailable() from None
        return Response(
            MCPStoredResultResponseSerializer({"download_url": url, "expires_in": MCP_RESULT_FILE_URL_TTL_SECONDS}).data
        )

    @validated_request(
        request_serializer=DocsSearchRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=DocsSearchResponseSerializer,
                description="Markdown-formatted documentation results.",
            ),
        },
        summary="Search PostHog documentation",
        description=(
            "Run a hybrid (semantic + full-text) RAG search over the PostHog documentation via "
            "Inkeep. Returns a markdown body with title, URL, and excerpt for each match for the "
            "agent to cite back to the user."
        ),
        operation_id="docs_search",
        tags=["docs"],
    )
    @action(detail=False, methods=["POST"], url_path="docs_search", required_scopes=["project:read"])
    def docs_search(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        if not settings.INKEEP_API_KEY:
            raise _DocsSearchUnavailable()

        query = cast(dict, request.validated_data)["query"]
        client = AsyncOpenAI(base_url="https://api.inkeep.com/v1/", api_key=settings.INKEEP_API_KEY)

        try:
            content = async_to_sync(_run_inkeep_docs_search)(client, query, self.team)
        except Exception as e:
            logger.exception("Error running docs_search", extra={"error": str(e)})
            capture_exception(e, properties={"tag": "mcp", "tool_name": "docs_search"})
            return Response(
                {"content": "The tool raised an internal error. Do not immediately retry the tool call."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(DocsSearchResponseSerializer({"content": content}).data)

    @extend_schema(
        parameters=[OpenApiParameter("tool_name", OpenApiTypes.STR, OpenApiParameter.PATH)],
        request=MCPToolRequest,
        responses={200: MCPToolResponse},
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="(?P<tool_name>[^/.]+)",
    )
    def invoke_tool(self, request: Request, tool_name: str, *args, **kwargs) -> Response:
        """
        Invoke an MCP tool by name.

        This endpoint allows MCP callers to invoke Max AI tools directly
        without going through the full LangChain conversation flow.

        Scopes are resolved dynamically per tool via dangerously_get_required_scopes.
        """
        tool = mcp_tool_registry.get(
            tool_name, team=self.team, user=cast(User, request.user), event_source=get_event_source(request)
        )
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

        error_id = str(uuid4())
        try:

            async def execute_tool() -> str | MCPToolResult:
                # Lower layers may capture the exception before it reaches this handler.
                with (
                    exception_context(error_id=error_id),
                    tags_context(feature=Feature.MCP, team_id=self.team.pk, org_id=self.team.organization_id),
                ):
                    return await tool.execute(validated_args)

            result = async_to_sync(execute_tool)()
        except MaxToolError as e:
            return Response(
                {
                    "success": False,
                    "content": f"Tool failed: {e.to_summary()}.{e.retry_hint}",
                    "error_type": e.error_type,
                    **({"error_code": e.error_code} if e.error_code else {}),
                }
            )
        except Exception as e:
            logger.exception(
                "Error calling tool", extra={"tool_name": tool_name, "error": str(e), "error_id": error_id}
            )
            capture_exception(e, properties={"tag": "mcp", "args": args_data, "error_id": error_id})
            return Response(
                {
                    "success": False,
                    "content": (
                        "The tool raised an internal error. Do not immediately retry the tool call. "
                        f"Error id: {error_id}"
                    ),
                }
            )

        if isinstance(result, str):
            result = MCPToolResult(content=result)
        return Response({"success": True, **result.model_dump(exclude_none=True)})


async def _fetch_inkeep_payload(client: AsyncOpenAI, query: str) -> dict | None:
    response = await client.chat.completions.create(
        model="inkeep-rag",
        messages=[{"role": "user", "content": query}],
    )
    raw = response.choices[0].message.content if response.choices else None
    return json.loads(raw) if raw else None


async def _run_inkeep_docs_search(client: AsyncOpenAI, query: str, team: Team) -> str:
    payload = await fetch_inkeep_with_shadow(
        team=team,
        query=query,
        fetch_inkeep=lambda: _fetch_inkeep_payload(client, query),
        surface="mcp",
    )
    return format_inkeep_docs_response(payload, include_system_reminder=False)
