"""DRF views for engineering_analytics.

Named, typed read endpoints over the curated PR/CI query builders. Each action
runs curated HogQL privately (no global view registration) and returns a typed
contract. These same endpoints back both the MCP tools and the UI:

- ``ci_cards`` — backlog headline counts.
- ``pull_requests`` — PR list with head-SHA CI rollup.
- ``workflow_health`` — per-workflow CI health over a window.
- ``pr_lifecycle`` — a single PR's header plus its ordered CI timeline.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.facade.contracts import GitHubSourceNotConnectedError
from products.engineering_analytics.backend.presentation.serializers import (
    CICardSummarySerializer,
    PRLifecycleSerializer,
    PullRequestListSerializer,
    WorkflowHealthItemSerializer,
)

ENGINEERING_ANALYTICS_TAG = "engineering_analytics"

_REPO = OpenApiParameter(
    name="repo",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Optional 'owner/name' repository to disambiguate when the PR number exists in more than one "
    "connected repo.",
)

_DATE_FROM = OpenApiParameter(
    name="date_from",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d.",
)

_DATE_TO = OpenApiParameter(
    name="date_to",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Window end: relative or ISO8601. Defaults to now.",
)

_SOURCE_ID = OpenApiParameter(
    name="source_id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub "
    "source when the team has more than one.",
)


def _bad_request(exc: ValueError, *, fallback: str) -> Response:
    return Response({"detail": str(exc) or fallback}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=[ENGINEERING_ANALYTICS_TAG])
class EngineeringAnalyticsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """PR and CI lifecycle analytics over the GitHub warehouse data."""

    scope_object = "engineering_analytics"
    scope_object_read_actions = ["ci_cards", "pull_requests", "workflow_health", "pr_lifecycle"]
    scope_object_write_actions: list[str] = []

    def handle_exception(self, exc: Exception) -> Response:
        # No GitHub warehouse source connected — every action degrades the same way.
        if isinstance(exc, GitHubSourceNotConnectedError):
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return super().handle_exception(exc)

    @extend_schema(
        operation_id="engineering_analytics_ci_cards",
        parameters=[_SOURCE_ID],
        responses={
            200: CICardSummarySerializer,
            400: OpenApiResponse(description="Invalid source_id."),
        },
        description=(
            "Headline counts for the open-PR backlog: open PRs, distinct repos, stuck PRs (open, non-draft, "
            "non-bot, older than 7 days), and PRs with failing CI. The failing-CI count rests on the head-SHA "
            "join and can lag until late CI completions settle."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def ci_cards(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_ci_cards(
                team=self.team,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid source_id")
        return Response(CICardSummarySerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_pull_requests",
        parameters=[_DATE_FROM, _SOURCE_ID],
        responses={
            200: PullRequestListSerializer,
            400: OpenApiResponse(description="Invalid date_from or source_id."),
        },
        description=(
            "Open pull requests plus any merged or closed since date_from (default -30d), newest first, each with "
            "its head-SHA CI rollup. The list is capped; when more match, `truncated` is true and the ci_cards "
            "counts can exceed it. open_to_merge_seconds is coarse — it fuses draft and ready-for-review time; "
            "CI counts can lag until late completions settle."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def pull_requests(self, request: Request, **kwargs) -> Response:
        try:
            result = api.list_pull_requests(
                team=self.team,
                date_from=request.query_params.get("date_from") or None,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date_from or source_id")
        return Response(PullRequestListSerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_workflow_health",
        parameters=[_DATE_FROM, _DATE_TO, _SOURCE_ID],
        responses={
            200: WorkflowHealthItemSerializer(many=True),
            400: OpenApiResponse(
                description="Invalid date_from, date_to, or source_id, or a window longer than 366 days."
            ),
        },
        description=(
            "Per-workflow CI health over a window (default last 30 days, maximum 366 days): run count, success "
            "rate, p50/p95 duration over completed runs, last failure time, and a zero-filled daily run history. "
            "Use this for 'is CI getting slower' and 'which workflow is the long pole'; compare two windows to "
            "get a trend."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def workflow_health(self, request: Request, **kwargs) -> Response:
        try:
            result = api.list_workflow_health(
                team=self.team,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date_from, date_to, or source_id")
        return Response(WorkflowHealthItemSerializer(instance=result, many=True).data)

    @extend_schema(
        operation_id="engineering_analytics_pr_lifecycle",
        parameters=[
            OpenApiParameter(
                name="pr_number",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Pull request number to inspect.",
            ),
            _REPO,
            _SOURCE_ID,
        ],
        responses={
            200: PRLifecycleSerializer,
            400: OpenApiResponse(description="Missing or non-integer pr_number, or invalid repo or source_id."),
            404: OpenApiResponse(description="No pull request with that number in the warehouse."),
        },
        description=(
            "The timeline of a single pull request: header plus ordered events (opened, CI started/finished, "
            "merged or closed). Use this to answer 'where is this PR stuck and what happened to it'. This is a "
            "partial view: review and comment events are not yet available."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def pr_lifecycle(self, request: Request, **kwargs) -> Response:
        raw_pr_number = request.query_params.get("pr_number")
        if raw_pr_number is None:
            return Response({"detail": "pr_number must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            pr_number = int(raw_pr_number)
        except ValueError:
            return Response({"detail": "pr_number must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = api.get_pr_lifecycle(
                team=self.team,
                pr_number=pr_number,
                repo=request.query_params.get("repo") or None,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid repo or source_id")
        if result is None:
            return Response({"detail": "Pull request not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(PRLifecycleSerializer(instance=result).data)
