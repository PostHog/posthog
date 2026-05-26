from typing import Any, cast

from django.db.models import QuerySet

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
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
    MCPIntentClusterSnapshotSerializer,
    MCPMissingCapabilityCreateSerializer,
    MCPSessionSerializer,
    MCPToolCallSerializer,
)


class MCPAnalyticsPagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = 500


class MCPSessionPagination(LimitOffsetPagination):
    """Returns ``{results, has_next}`` instead of a count-based envelope. The list is an
    on-the-fly ClickHouse aggregate with no cheap total, so ``has_next`` comes from the
    logic layer over-fetching one row rather than a count query.
    """

    default_limit = 100
    max_limit = 500

    def get_paginated_response(self, data: Any, *, has_next: bool = False) -> Response:
        return Response({"results": data, "has_next": has_next})

    def get_paginated_response_schema(self, schema: dict) -> dict:
        return {
            "type": "object",
            "required": ["results", "has_next"],
            "properties": {
                "results": schema,
                "has_next": {
                    "type": "boolean",
                    "description": "Whether more results exist beyond this page; the client fetches the next page with a larger offset.",
                },
            },
        }


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
    pagination_class = MCPSessionPagination

    def dangerously_get_queryset(self) -> QuerySet:
        # Sessions live in ClickHouse, not a Django model, but GenericViewSet still needs a
        # queryset for its plumbing. The model is arbitrary — we borrow MCPAnalyticsSubmission
        # (a plain manager) so .none() can't trip a team-scoped manager's guard.
        return MCPAnalyticsSubmission.objects.none()

    @extend_schema(
        operation_id="mcp_analytics_sessions_list",
        description="List MCP sessions for the current project, derived by grouping mcp_tool_call events by $mcp_session_id. Ordered by newest session start first by default.",
        parameters=[
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Case-insensitive substring filter matched against session_id, distinct_id, mcp_client_name, and tools_used.",
            ),
            OpenApiParameter(
                name="order_by",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Sort column. Allowed: session_id, session_start, session_end, "
                    "duration_seconds, tool_call_count, mcp_client_name, distinct_id. "
                    "Prefix with '-' for descending. Defaults to '-session_start' (newest sessions first)."
                ),
            ),
        ],
        responses={200: MCPSessionSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Instantiate the concrete class (not self.pagination_class()) so the typed
        # get_paginated_response(has_next=...) is visible to the type checker.
        paginator = MCPSessionPagination()
        limit = paginator.get_limit(request) or paginator.default_limit
        offset = paginator.get_offset(request)
        search = request.query_params.get("search", "")
        order_by = request.query_params.get("order_by", "")
        page = api.list_mcp_sessions(self.team, limit=limit, offset=offset, search=search, order_by=order_by)
        serializer = self.get_serializer(page.results, many=True)
        return paginator.get_paginated_response(serializer.data, has_next=page.has_next)

    @extend_schema(
        operation_id="mcp_analytics_sessions_tool_calls",
        description="List all mcp_tool_call events that belong to a given $session_id, in chronological order.",
        responses={200: MCPToolCallSerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="tool_calls")
    def tool_calls(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        tool_calls = api.list_mcp_tool_calls(self.team, session_id=str(pk or ""))
        serializer = MCPToolCallSerializer(tool_calls, many=True)
        # has_next is always false: this returns the whole (capped) call list, not a page.
        # The field exists because the viewset's paginator shapes the response schema.
        return Response({"results": serializer.data, "has_next": False})


@extend_schema(tags=["mcp_analytics"])
class MCPIntentClusterViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = MCPIntentClusterSnapshotSerializer
    permission_classes = [IsAuthenticated, SingleTenancyOrAdmin]
    scope_object = "INTERNAL"
    pagination_class = None

    def dangerously_get_queryset(self) -> QuerySet:
        # Snapshots are read directly via the facade; this satisfies GenericViewSet plumbing.
        return MCPAnalyticsSubmission.objects.none()

    @extend_schema(
        operation_id="mcp_analytics_intent_clusters_retrieve",
        description=(
            "Return the most recent intent cluster snapshot for the current project. "
            "Returns an empty IDLE snapshot when no clustering run has happened yet."
        ),
        responses={200: MCPIntentClusterSnapshotSerializer},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        snapshot = api.get_intent_cluster_snapshot(self.team)
        serializer = self.get_serializer(snapshot)
        return Response(serializer.data)

    @extend_schema(
        operation_id="mcp_analytics_intent_clusters_recompute",
        description=(
            "Trigger an asynchronous recompute of the intent cluster snapshot. The task runs in the "
            "background; poll the GET endpoint for progress (status transitions to 'idle' or 'error')."
        ),
        request=None,
        responses={202: MCPIntentClusterSnapshotSerializer},
    )
    @action(detail=False, methods=["post"], url_path="recompute")
    def recompute(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        api.trigger_intent_cluster_recompute(self.team, cast(User, request.user))
        snapshot = api.get_intent_cluster_snapshot(self.team)
        serializer = self.get_serializer(snapshot)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)


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
