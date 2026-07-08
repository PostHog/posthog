from datetime import datetime
from typing import Any, cast

from django.db.models import QuerySet
from django.utils.dateparse import parse_datetime

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission

from products.mcp_analytics.backend import logic
from products.mcp_analytics.backend.facade import api, contracts, enums
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission

from .serializers import (
    MCP_SESSION_LIST_DEFAULT_LIMIT,
    MCP_SESSION_LIST_MAX_LIMIT,
    MCPActivityOverviewSerializer,
    MCPAnalyticsSubmissionSerializer,
    MCPFeedbackCreateSerializer,
    MCPIntentClusterSnapshotSerializer,
    MCPIntentDigestSerializer,
    MCPMissingCapabilityCreateSerializer,
    MCPSessionIntentSerializer,
    MCPSessionListQuerySerializer,
    MCPSessionSerializer,
    MCPSessionToolCallsQuerySerializer,
    MCPToolCallSerializer,
)


def _parse_detail_date_from(raw: str | None) -> datetime | None:
    """Parse the optional session-start bound for detail queries (an absolute ISO timestamp).

    Returns None on missing or unparseable input so the logic layer falls back to its default
    lookback rather than 400-ing — the bound is only a scan-pruning hint, never a filter.
    """
    return parse_datetime(raw) if raw else None


class MCPAnalyticsPagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = 500


class MCPSessionPagination(LimitOffsetPagination):
    """Returns ``{results, has_next}`` instead of a count-based envelope. The list is an
    on-the-fly ClickHouse aggregate with no cheap total, so ``has_next`` comes from the
    logic layer over-fetching one row rather than a count query.
    """

    default_limit = MCP_SESSION_LIST_DEFAULT_LIMIT
    max_limit = MCP_SESSION_LIST_MAX_LIMIT

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


class BaseMCPAnalyticsSubmissionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = MCPAnalyticsSubmissionSerializer
    # Alpha product: gated behind the mcp-analytics feature flag at the API layer (matching
    # the UI flag) rather than hidden behind a staff-only lock. create -> write, list -> read
    # map to the default scope actions.
    scope_object = "mcp_analytics"
    posthog_feature_flag = "mcp-analytics"
    permission_classes = [PostHogFeatureFlagPermission]
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


class MCPSessionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = MCPSessionSerializer
    scope_object = "mcp_analytics"
    # tool_calls and activity_overview are GETs (read); generate_intent is a POST that computes +
    # persists the intent summary, so it maps to the write scope. The default read/write action
    # lists don't cover custom @action names, so APIScopePermission would otherwise reject token access.
    scope_object_read_actions = ["list", "retrieve", "tool_calls", "activity_overview"]
    scope_object_write_actions = ["generate_intent", "intent_digest"]
    posthog_feature_flag = "mcp-analytics"
    permission_classes = [PostHogFeatureFlagPermission]
    pagination_class = MCPSessionPagination

    def dangerously_get_queryset(self) -> QuerySet:
        # Sessions live in ClickHouse, not a Django model, but GenericViewSet still needs a
        # queryset for its plumbing. The model is arbitrary — we borrow MCPAnalyticsSubmission
        # (a plain manager) so .none() can't trip a team-scoped manager's guard.
        return MCPAnalyticsSubmission.objects.none()

    @validated_request(
        query_serializer=MCPSessionListQuerySerializer,
        responses={200: OpenApiResponse(response=MCPSessionSerializer(many=True))},
        operation_id="mcp_analytics_sessions_list",
        description="List MCP sessions for the current project, derived by grouping $mcp_tool_call events by $mcp_session_id. Ordered by newest session start first by default.",
    )
    def list(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        params = request.validated_query_data
        page = api.list_mcp_sessions(
            self.team,
            limit=params["limit"],
            offset=params["offset"],
            search=params["search"],
            order_by=params["order_by"],
            date_from=params.get("date_from") or None,
            date_to=params.get("date_to") or None,
        )
        serializer = self.get_serializer(page.results, many=True)
        # Instantiate the concrete class (not self.pagination_class()) so the typed
        # get_paginated_response(has_next=...) is visible to the type checker.
        return MCPSessionPagination().get_paginated_response(serializer.data, has_next=page.has_next)

    @validated_request(
        query_serializer=MCPSessionToolCallsQuerySerializer,
        responses={200: OpenApiResponse(response=MCPToolCallSerializer(many=True))},
        operation_id="mcp_analytics_sessions_tool_calls",
        description="List a page of the $mcp_tool_call events that belong to a given $session_id, in chronological order.",
    )
    @action(detail=True, methods=["get"], url_path="tool_calls")
    def tool_calls(self, request: ValidatedRequest, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        params = request.validated_query_data
        page = api.list_mcp_tool_calls(
            self.team,
            session_id=str(pk or ""),
            limit=params["limit"],
            offset=params["offset"],
            date_from=params.get("date_from"),
        )
        serializer = MCPToolCallSerializer(page.results, many=True)
        return MCPSessionPagination().get_paginated_response(serializer.data, has_next=page.has_next)

    @extend_schema(
        operation_id="mcp_analytics_sessions_generate_intent",
        description=(
            "Generate (or return the cached) LLM summary of the agent's goal for a session, derived from its "
            "recorded $mcp_intents. The first call summarises and persists the result; subsequent calls return "
            "the stored summary."
        ),
        request=None,
        parameters=[
            OpenApiParameter(
                name="date_from",
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Absolute ISO timestamp lower bound for the intent scan — pass the session's "
                    "start so older sessions resolve. Defaults to a 7-day lookback when omitted."
                ),
            ),
        ],
        responses={200: MCPSessionIntentSerializer},
    )
    @action(detail=True, methods=["post"], url_path="generate_intent")
    def generate_intent(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        session_id = str(pk or "")
        if not session_id:
            return Response({"detail": "session_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        date_from = _parse_detail_date_from(request.query_params.get("date_from"))
        try:
            intent = api.generate_session_intent(self.team, session_id=session_id, date_from=date_from)
        except contracts.IntentGenerationUnavailable:
            return Response(
                {"detail": "Intent generation is unavailable (LLM not configured)."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        serializer = MCPSessionIntentSerializer({"session_id": session_id, "intent": intent})
        return Response(serializer.data)

    @extend_schema(
        operation_id="mcp_analytics_sessions_intent_digest",
        description=(
            "Generate (or return the cached) LLM digest of what agents are trying to do with this MCP server, "
            "derived from the most recent recorded $mcp_intents across all sessions. Content-addressed cache: "
            "only regenerates when new intents arrive. Powers the dashboard's low-volume activity stage."
        ),
        request=None,
        responses={
            200: MCPIntentDigestSerializer,
            503: OpenApiResponse(description="Intent digest generation is unavailable (LLM not configured)."),
        },
    )
    @action(detail=False, methods=["post"], url_path="intent_digest")
    def intent_digest(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            digest = api.generate_intent_digest(self.team)
        except contracts.IntentGenerationUnavailable:
            return Response(
                {"detail": "Intent digest generation is unavailable (LLM not configured)."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(MCPIntentDigestSerializer(digest).data)

    @extend_schema(
        operation_id="mcp_analytics_sessions_activity_overview",
        description=(
            "Aggregate counters, top tools, agent clients, and the most recent tool calls for the last 30 days, "
            "computed in one request. Powers the dashboard's activity view; always computed fresh so polling "
            "callers watch data arrive."
        ),
        responses={200: MCPActivityOverviewSerializer},
    )
    @action(detail=False, methods=["get"], url_path="activity_overview", pagination_class=None)
    def activity_overview(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        overview = api.get_activity_overview(self.team)
        return Response(MCPActivityOverviewSerializer(overview).data)


class MCPIntentClusterViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = MCPIntentClusterSnapshotSerializer
    scope_object = "mcp_analytics"
    # recompute is a POST that kicks off the async clustering task (a state change), so it maps to
    # the write scope; the snapshot read stays on the read scope.
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["recompute"]
    posthog_feature_flag = "mcp-analytics"
    permission_classes = [PostHogFeatureFlagPermission]
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
