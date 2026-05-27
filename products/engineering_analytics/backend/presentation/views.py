"""DRF views for engineering_analytics.

Read-only endpoints backing the MCP tools. Each action parses PostHog-convention
query parameters, calls the facade with the request team, and serializes the
returned contract type. No business logic here — that lives behind the facade.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api
from .serializers import PRLifecycleSerializer, TimeToMergeSerializer, WorkflowReportSerializer

ENGINEERING_ANALYTICS_TAG = "engineering_analytics"

_DATE_FROM = OpenApiParameter(
    name="date_from",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    default="-7d",
    description="Start of the window: a relative string like '-7d' or an ISO8601 timestamp. Defaults to '-7d'.",
)
_DATE_TO = OpenApiParameter(
    name="date_to",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="End of the window: a relative string or ISO8601 timestamp. Omit for 'now'.",
)
_REPO = OpenApiParameter(
    name="repo",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Optional 'owner/name' repository. In v1 this only labels the response; it does not filter rows.",
)


@extend_schema(tags=[ENGINEERING_ANALYTICS_TAG])
class EngineeringAnalyticsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """PR and CI lifecycle analytics over the GitHub warehouse data."""

    scope_object = "engineering_analytics"
    scope_object_read_actions = ["workflow_report", "time_to_merge", "pr_lifecycle"]
    scope_object_write_actions: list[str] = []

    @extend_schema(
        operation_id="engineering_analytics_workflow_report",
        parameters=[_DATE_FROM, _DATE_TO, _REPO],
        responses={200: WorkflowReportSerializer},
        description=(
            "Which CI workflows are the long poles right now. Returns each GitHub Actions workflow with its run "
            "count, success rate, median and p95 duration, and last failure, slowest median first. Use this to "
            "answer 'what's slow in CI this week' or to check whether a known long-pole workflow is holding up a PR."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def workflow_report(self, request: Request, **kwargs) -> Response:
        result = api.get_workflow_report(
            team=self.team,
            date_from=request.query_params.get("date_from", "-7d"),
            date_to=request.query_params.get("date_to") or None,
            repo=request.query_params.get("repo") or None,
        )
        return Response(WorkflowReportSerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_time_to_merge",
        parameters=[
            _DATE_FROM,
            _DATE_TO,
            _REPO,
            OpenApiParameter(
                name="group_by_author",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                default=False,
                description="Split results per author handle instead of one overall bucket.",
            ),
        ],
        responses={200: TimeToMergeSerializer},
        description=(
            "How long pull requests take from open to merge. Returns median and p95 seconds and a PR count, either "
            "overall or split per author. Bots and drafts are excluded. This is a coarse metric: it combines draft "
            "and ready-for-review time, since the warehouse holds current state, not a transition history."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def time_to_merge(self, request: Request, **kwargs) -> Response:
        result = api.get_time_to_merge(
            team=self.team,
            date_from=request.query_params.get("date_from", "-7d"),
            date_to=request.query_params.get("date_to") or None,
            repo=request.query_params.get("repo") or None,
            group_by_author=_parse_bool(request.query_params.get("group_by_author")),
        )
        return Response(TimeToMergeSerializer(instance=result).data)

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
        ],
        responses={
            200: PRLifecycleSerializer,
            400: OpenApiResponse(description="Missing or non-integer pr_number."),
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
        try:
            pr_number = int(raw_pr_number)
        except (TypeError, ValueError):
            return Response({"detail": "pr_number must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        result = api.get_pr_lifecycle(
            team=self.team,
            pr_number=pr_number,
            repo=request.query_params.get("repo") or None,
        )
        if result is None:
            return Response({"detail": "Pull request not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(PRLifecycleSerializer(instance=result).data)


def _parse_bool(value: str | None) -> bool:
    return value is not None and value.lower() in ("1", "true", "yes")
