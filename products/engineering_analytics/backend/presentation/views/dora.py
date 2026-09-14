"""DORA deploy-metrics read."""

from functools import partial

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.presentation.serializers.dora import (
    DoraEnvironmentQuerySerializer,
    DoraOverviewSerializer,
)
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
    many=True,
    location=OpenApiParameter.QUERY,
    required=False,
    # Explicit explode: the generated client only emits repeated `environment=` keys for params the
    # spec marks explode, and Django's getlist needs repeated keys — a comma-joined value matches no
    # environment.
    explode=True,
    description="Deploy environment(s) to scope to, repeatable (from the response's `environments` list). Omit "
    "to include all persistent environments marked production or named prod/production (including regional "
    "suffixes), falling back to the busiest persistent environment when none match. Explicit names are trimmed, "
    "deduplicated, and validated against the source, including transient environments. Blank or unknown names "
    "are rejected with a 400 response.",
)

_GRANULARITY = OpenApiParameter(
    name="granularity",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    enum=["hour", "day", "week"],
    description="Bucket width for every series. Omit to pick one that fits the window: hour up to 48h, day up "
    "to 90 days, week beyond.",
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
        parameters=[
            _DATE_FROM,
            _DATE_TO,
            _ENVIRONMENT,
            _GITHUB_TEAM,
            _GRANULARITY,
            _SOURCE_ID,
            _REPO,
        ],
        responses={
            200: DoraOverviewSerializer,
            400: OpenApiResponse(description="Invalid environment, date_from, date_to, granularity, or source_id."),
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
            query = DoraEnvironmentQuerySerializer(
                data=request.query_params,
                context={
                    "get_environment_choices": partial(
                        api.get_dora_environment_choices,
                        team=self.team,
                        date_from=request.query_params.get("date_from") or None,
                        date_to=request.query_params.get("date_to") or None,
                        source_id=request.query_params.get("source_id") or None,
                        repo=request.query_params.get("repo") or None,
                        user_access_control=self.user_access_control,
                    )
                },
            )
            query.is_valid(raise_exception=True)
            result = api.get_dora_overview(
                team=self.team,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                validated_environments=query.validated_data.get("environment"),
                github_team=request.query_params.get("github_team") or None,
                granularity=request.query_params.get("granularity") or None,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date_from, date_to, granularity, or source_id")
        return Response(DoraOverviewSerializer(instance=result).data)
