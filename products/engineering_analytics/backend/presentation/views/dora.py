"""DORA deploy-metrics read."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.presentation.serializers.dora import DoraOverviewSerializer
from products.engineering_analytics.backend.presentation.views._base import (
    _DATE_FROM,
    _DATE_TO,
    _REPO,
    _SOURCE_ID,
    EngineeringAnalyticsViewSetBase,
    _bad_request,
)

_ENVIRONMENT = OpenApiParameter(
    name="environment",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Exact deploy environment to scope to (from the response's `environments` list). Omit to scope "
    "to production-marked deployments, falling back to every persistent (non-transient) environment when none "
    "are marked production.",
)

_GITHUB_TEAM = OpenApiParameter(
    name="github_team",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="GitHub team slug (from the response's `github_teams` list) to narrow the PR-scoped "
    "merge-to-deploy figures to that team's authors. Deploy counts stay repo-wide. Needs the team-membership "
    "snapshot synced; without it the merge-to-deploy figures return empty rather than silently unfiltered.",
)


class DoraActionsMixin(EngineeringAnalyticsViewSetBase):
    READ_ACTIONS = ["dora"]

    @extend_schema(
        operation_id="engineering_analytics_dora",
        parameters=[_DATE_FROM, _DATE_TO, _ENVIRONMENT, _GITHUB_TEAM, _SOURCE_ID, _REPO],
        responses={
            200: DoraOverviewSerializer,
            400: OpenApiResponse(description="Invalid date_from, date_to, or source_id."),
        },
        description=(
            "DORA-style deploy metrics over the GitHub deployments + deployment_statuses warehouse pair, each "
            "headline with its previous-window twin: deployment frequency, merge-to-deploy lead time (with a "
            "per-bucket box-plot series), and honest proxies for change failure rate and time to restore "
            "(deploy-status based — no incident data is linked). deploy_data_available is false when the deploy "
            "tables aren't synced."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def dora(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_dora_overview(
                team=self.team,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                environment=request.query_params.get("environment") or None,
                github_team=request.query_params.get("github_team") or None,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date_from, date_to, or source_id")
        return Response(DoraOverviewSerializer(instance=result).data)
