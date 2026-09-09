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
from posthog.models.user import User
from posthog.renderers import SafeJSONRenderer

from ee.hogai.mcp_tool import mcp_tool_registry
from ee.hogai.tool_errors import MaxToolAccessDeniedError, MaxToolError, MaxToolRetryableError, MaxToolTransientError
from ee.hogai.tools.search import format_inkeep_docs_response

logger = get_logger(__name__)

# What a caller may do with the same input after this failure. Callers are agents, so the contract
# has to be in the content string they read, not only in the fields beside it.
_RETRY_GUIDANCE = {
    "never": "Retrying with the same input will not help.",
    "once": "Retrying once with the same input is safe.",
    "adjusted": "Retrying is safe once you adjust the input.",
}


def _failure_response(
    *,
    category: str,
    cause: str,
    retry: str,
    tool_name: str,
    correlation_id: str,
    http_status: int | None = None,
) -> Response:
    """Answer a failed tool call with a cause, a retry verdict, and an ID that finds the trace."""
    body = {
        "success": False,
        "content": (
            f"Tool `{tool_name}` failed ({category}): {cause} "
            f"{_RETRY_GUIDANCE[retry]} Correlation ID: {correlation_id}."
        ),
        "error": {
            "category": category,
            "retry": retry,
            "tool": tool_name,
            "correlation_id": correlation_id,
        },
    }
    return Response(body, status=http_status) if http_status else Response(body)


def _max_tool_error_category(error: MaxToolError) -> str:
    if isinstance(error, MaxToolAccessDeniedError):
        return "permission"
    if isinstance(error, MaxToolTransientError):
        return "transient"
    if isinstance(error, MaxToolRetryableError):
        return "invalid_input"
    return "fatal"


def _max_tool_error_cause(error: MaxToolError, max_length: int = 500) -> str:
    """The tool's own message, without the class name that `category` already carries."""
    cause = str(error).strip()
    if len(cause) > max_length:
        cause = cause[:max_length] + "…"
    return f"{cause}."


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


class MCPToolsViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "project"
    serializer_class = _FallbackSerializer

    renderer_classes = [SafeJSONRenderer]

    def dangerously_get_required_scopes(self, request: Request, view: View) -> list[str] | None:
        if self.action == "invoke_tool":
            tool_name = self.kwargs.get("tool_name", "")
            scopes = mcp_tool_registry.get_scopes(tool_name)
            return scopes or None
        return None

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
            content = async_to_sync(_run_inkeep_docs_search)(client, query)
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
        responses={200: OpenApiTypes.OBJECT},
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
            return _failure_response(
                category="unknown_tool",
                cause=f"No tool named `{tool_name}` is registered.",
                retry="never",
                tool_name=tool_name,
                correlation_id=uuid4().hex,
                http_status=status.HTTP_404_NOT_FOUND,
            )

        args_data = request.data.get("args", {})

        try:
            validated_args = tool.args_schema.model_validate(args_data)
        except pydantic.ValidationError as e:
            return _failure_response(
                category="invalid_input",
                cause=f"The arguments did not match the tool schema:\n{e.errors(include_url=False)}",
                retry="adjusted",
                tool_name=tool_name,
                correlation_id=uuid4().hex,
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        try:

            async def execute_tool() -> str:
                with tags_context(feature=Feature.MCP, team_id=self.team.pk, org_id=self.team.organization_id):
                    return await tool.execute(validated_args)

            content = async_to_sync(execute_tool)()
        except MaxToolError as e:
            return _failure_response(
                category=_max_tool_error_category(e),
                cause=_max_tool_error_cause(e),
                retry=e.retry_strategy,
                tool_name=tool_name,
                correlation_id=uuid4().hex,
            )
        except Exception as e:
            # An unclassified exception is a defect, so the caller gets an ID rather than the
            # message: only the ID is guaranteed to be free of internals, and it ties their report
            # to the captured trace.
            correlation_id = uuid4().hex
            logger.exception(
                "Error calling tool",
                extra={"tool_name": tool_name, "error": str(e), "correlation_id": correlation_id},
            )
            capture_exception(
                e,
                properties={"tag": "mcp", "args": args_data, "tool_name": tool_name, "correlation_id": correlation_id},
            )
            return _failure_response(
                category="internal",
                cause="The tool hit an unexpected error, which has been reported to PostHog.",
                retry="never",
                tool_name=tool_name,
                correlation_id=correlation_id,
            )

        return Response({"success": True, "content": content})


async def _run_inkeep_docs_search(client: AsyncOpenAI, query: str) -> str:
    response = await client.chat.completions.create(
        model="inkeep-rag",
        messages=[{"role": "user", "content": query}],
    )
    raw = response.choices[0].message.content if response.choices else None
    payload = json.loads(raw) if raw else None
    return format_inkeep_docs_response(payload, include_system_reminder=False)
