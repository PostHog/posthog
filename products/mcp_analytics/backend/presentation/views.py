from datetime import datetime
from typing import Any, cast

from django.db.models import QuerySet
from django.utils.dateparse import parse_datetime

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.user import User
from posthog.permissions import SingleTenancyOrAdmin

from products.mcp_analytics.backend import logic
from products.mcp_analytics.backend.facade import api, contracts, enums
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission

from .serializers import (
    MCPAnalyticsSubmissionSerializer,
    MCPFeedbackCreateSerializer,
    MCPMissingCapabilityCreateSerializer,
    MCPSessionSerializer,
    MCPToolCallListResponseSerializer,
    MCPToolCallSerializer,
)


def _parse_iso_datetime_param(value: str | None, param_name: str) -> datetime | None:
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValidationError({param_name: f"Expected an ISO 8601 datetime, got {value!r}."})
    return parsed


class MCPAnalyticsPagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = 500


@extend_schema(tags=["mcp_analytics"])
class BaseMCPAnalyticsSubmissionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = MCPAnalyticsSubmissionSerializer
    # Keep these endpoints staff-only until the MCP tools and auth model are ready for customer traffic.
    permission_classes = [IsAuthenticated, SingleTenancyOrAdmin]
    scope_object = "INTERNAL"
    pagination_class = MCPAnalyticsPagination
    user_action_name: str = ""

    def _submission_context(self, validated_data: dict[str, Any]) -> contracts.SubmissionContext:
        return contracts.SubmissionContext(
            attempted_tool=validated_data.get("attempted_tool", ""),
            mcp_client_name=validated_data.get("mcp_client_name", ""),
            mcp_client_version=validated_data.get("mcp_client_version", ""),
            mcp_protocol_version=validated_data.get("mcp_protocol_version", ""),
            mcp_transport=validated_data.get("mcp_transport", ""),
            mcp_session_id=validated_data.get("mcp_session_id", ""),
            mcp_trace_id=validated_data.get("mcp_trace_id", ""),
        )

    def _report_submission_created(self, request: Request, submission: contracts.Submission) -> None:
        report_user_action(
            cast(User, request.user),
            self.user_action_name,
            {
                "submission_id": str(submission.id),
                "kind": submission.kind,
                "attempted_tool": submission.attempted_tool,
                "mcp_client_name": submission.mcp_client_name,
                "mcp_session_id_present": bool(submission.mcp_session_id),
                "mcp_trace_id_present": bool(submission.mcp_trace_id),
            },
            team=self.team,
            request=request,
        )

    def _list_response(self, request: Request, kind: enums.SubmissionKind) -> Response:
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(logic.list_submissions(self.team, kind), request, view=self)
        assert page is not None
        serializer = self.get_serializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class MCPFeedbackViewSet(BaseMCPAnalyticsSubmissionViewSet):
    user_action_name = "mcp analytics feedback created"

    @validated_request(
        request_serializer=MCPFeedbackCreateSerializer,
        responses={201: OpenApiResponse(response=MCPAnalyticsSubmissionSerializer)},
        operation_id="mcp_analytics_feedback_create",
        description="Create a new MCP feedback submission for the current project.",
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        submission = api.create_feedback_submission(
            self.team,
            cast(User, request.user),
            contracts.CreateFeedbackSubmission(
                goal=request.validated_data["goal"],
                feedback=request.validated_data["feedback"],
                category=request.validated_data["category"],
                context=self._submission_context(request.validated_data),
            ),
        )
        self._report_submission_created(request, submission)
        return Response(self.get_serializer(submission).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="mcp_analytics_feedback_list",
        description="List MCP feedback submissions for the current project, newest first.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._list_response(request, enums.SubmissionKind.FEEDBACK)


@extend_schema(tags=["mcp_analytics"])
class MCPSessionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = MCPSessionSerializer
    permission_classes = [IsAuthenticated, SingleTenancyOrAdmin]
    scope_object = "INTERNAL"
    pagination_class = MCPAnalyticsPagination

    def dangerously_get_queryset(self) -> QuerySet:
        # Sessions are aggregated from ClickHouse events, not from a Django model.
        # Returning an empty queryset satisfies DRF's GenericViewSet plumbing.
        return MCPAnalyticsSubmission.objects.none()

    @extend_schema(
        operation_id="mcp_analytics_sessions_list",
        description="List MCP sessions for the current project, derived by grouping mcp_tool_call events by $session_id. Ordered by most recent activity first.",
        responses={200: MCPSessionSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        paginator = self.pagination_class()
        limit = paginator.get_limit(request) or paginator.default_limit
        offset = paginator.get_offset(request)
        sessions = api.list_mcp_sessions(self.team, limit=limit, offset=offset)
        serializer = self.get_serializer(sessions, many=True)
        return Response({"results": serializer.data})

    @extend_schema(
        operation_id="mcp_analytics_sessions_tool_calls",
        description=(
            "List mcp_tool_call events that belong to a given $session_id, in chronological order. "
            "Bounded by an optional date_from / date_to window (defaults to the last 30 days) so the "
            "ClickHouse scan stays partition-pruned. Capped at 500 rows per response — when more "
            "matching events exist the response sets truncated=true."
        ),
        parameters=[
            OpenApiParameter(
                name="date_from",
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "ISO 8601 lower bound for the event timestamp. Pass the parent session's first_seen "
                    "(minus a small buffer) for the tightest window. Defaults to 30 days ago."
                ),
            ),
            OpenApiParameter(
                name="date_to",
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "ISO 8601 upper bound for the event timestamp. Pass the parent session's last_seen "
                    "(plus a small buffer) for the tightest window. Defaults to tomorrow."
                ),
            ),
        ],
        responses={200: MCPToolCallListResponseSerializer},
    )
    @action(detail=True, methods=["get"], url_path="tool_calls")
    def tool_calls(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        date_from = _parse_iso_datetime_param(request.query_params.get("date_from"), "date_from")
        date_to = _parse_iso_datetime_param(request.query_params.get("date_to"), "date_to")
        result = api.list_mcp_tool_calls(
            self.team,
            session_id=str(pk or ""),
            date_from=date_from,
            date_to=date_to,
        )
        serializer = MCPToolCallSerializer(result.tool_calls, many=True)
        return Response({"results": serializer.data, "truncated": result.truncated})


class MCPMissingCapabilityViewSet(BaseMCPAnalyticsSubmissionViewSet):
    user_action_name = "mcp analytics missing capability reported"

    @validated_request(
        request_serializer=MCPMissingCapabilityCreateSerializer,
        responses={201: OpenApiResponse(response=MCPAnalyticsSubmissionSerializer)},
        operation_id="mcp_analytics_missing_capabilities_create",
        description="Create a new missing capability report for the current project.",
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        submission = api.create_missing_capability_submission(
            self.team,
            cast(User, request.user),
            contracts.CreateMissingCapabilitySubmission(
                goal=request.validated_data["goal"],
                missing_capability=request.validated_data["missing_capability"],
                blocked=request.validated_data["blocked"],
                context=self._submission_context(request.validated_data),
            ),
        )
        self._report_submission_created(request, submission)
        return Response(self.get_serializer(submission).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="mcp_analytics_missing_capabilities_list",
        description="List missing capability reports for the current project, newest first.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._list_response(request, enums.SubmissionKind.MISSING_CAPABILITY)
