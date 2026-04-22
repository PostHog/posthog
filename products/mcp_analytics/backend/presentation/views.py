from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
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

from .serializers import (
    MCPAnalyticsSubmissionSerializer,
    MCPFeedbackCreateSerializer,
    MCPMissingCapabilityCreateSerializer,
)


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
