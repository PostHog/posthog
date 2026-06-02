"""DRF views for engineering_analytics.

The named deep tool over the curated read layer. ``pr_lifecycle`` assembles a
single PR's header plus its ordered CI timeline — a genuine cross-view assembly
that the generic SQL/MCP query surface can't express in one call. Aggregate
questions (CI health, time to merge) are answered by SQL over the
``engineering_analytics_*`` views, guided by the in-product skill, not by bespoke
endpoints here.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.presentation.serializers import PRLifecycleSerializer

ENGINEERING_ANALYTICS_TAG = "engineering_analytics"

_REPO = OpenApiParameter(
    name="repo",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Optional 'owner/name' repository to disambiguate when the PR number exists in more than one "
    "connected repo.",
)


@extend_schema(tags=[ENGINEERING_ANALYTICS_TAG])
class EngineeringAnalyticsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """PR and CI lifecycle analytics over the GitHub warehouse data."""

    scope_object = "engineering_analytics"
    scope_object_read_actions = ["pr_lifecycle"]
    scope_object_write_actions: list[str] = []

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
        if raw_pr_number is None:
            return Response({"detail": "pr_number must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            pr_number = int(raw_pr_number)
        except ValueError:
            return Response({"detail": "pr_number must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        result = api.get_pr_lifecycle(
            team=self.team,
            pr_number=pr_number,
            repo=request.query_params.get("repo") or None,
        )
        if result is None:
            return Response({"detail": "Pull request not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(PRLifecycleSerializer(instance=result).data)
