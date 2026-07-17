from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User

from products.web_analytics.backend.recap import build_team_recap
from products.web_analytics.backend.serializers import (
    WebAnalyticsRecapResponseSerializer,
    WeeklyDigestResponseSerializer,
)
from products.web_analytics.backend.weekly_digest import build_team_digest

MIN_DAYS = 1
MAX_DAYS = 90
DEFAULT_DAYS = 7


class _DigestQuerySerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=MIN_DAYS, max_value=MAX_DAYS, required=False, default=DEFAULT_DAYS)
    compare = serializers.BooleanField(required=False, default=True)


class WebAnalyticsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "web_analytics"
    scope_object_read_actions = ["weekly_digest", "recap"]
    serializer_class = WeeklyDigestResponseSerializer

    @extend_schema(
        operation_id="web_analytics_weekly_digest",
        summary="Summarize web analytics",
        description=(
            "Summarizes a project's web analytics over a lookback window (default 7 days): unique "
            "visitors, pageviews, sessions, bounce rate, and average session duration with "
            "period-over-period comparisons, plus the top 5 pages, top 5 traffic sources, and "
            "goal conversions."
        ),
        parameters=[
            OpenApiParameter(
                name="days",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                default=DEFAULT_DAYS,
                description=f"Lookback window in days ({MIN_DAYS}–{MAX_DAYS}). Defaults to {DEFAULT_DAYS}.",
            ),
            OpenApiParameter(
                name="compare",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                default=True,
                description=(
                    "When true (default), include period-over-period change for each metric "
                    "comparing against the prior equal-length period. Set to false to skip the "
                    "comparison query (faster)."
                ),
            ),
        ],
        responses={200: OpenApiResponse(response=WeeklyDigestResponseSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=False, methods=["get"], url_path="weekly_digest")
    def weekly_digest(self, request: "Request", **kwargs: object) -> Response:
        query_serializer = _DigestQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data
        digest = build_team_digest(
            self.team,
            days=params["days"],
            compare=params["compare"],
            user=request.user if isinstance(request.user, User) else None,
        )
        serializer = self.get_serializer(instance=digest)
        return Response(serializer.data)

    @extend_schema(
        operation_id="web_analytics_recap",
        summary="Weekly web analytics recap",
        description=(
            "The 'Wrapped'-style weekly recap: everything in the weekly digest (visitors, pageviews, "
            "sessions, bounce rate, average session duration with period-over-period comparisons, top "
            "pages, top sources, and goals) plus a single derived weekly persona and a short list of "
            "screenshot-worthy highlights for the period."
        ),
        parameters=[
            OpenApiParameter(
                name="days",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                default=DEFAULT_DAYS,
                description=f"Lookback window in days ({MIN_DAYS}–{MAX_DAYS}). Defaults to {DEFAULT_DAYS}.",
            ),
            OpenApiParameter(
                name="compare",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                default=True,
                description=(
                    "When true (default), include period-over-period change for each metric comparing "
                    "against the prior equal-length period. Set to false to skip the comparison query."
                ),
            ),
        ],
        responses={200: OpenApiResponse(response=WebAnalyticsRecapResponseSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=False, methods=["get"], url_path="recap")
    def recap(self, request: "Request", **kwargs: object) -> Response:
        query_serializer = _DigestQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data
        recap = build_team_recap(
            self.team,
            days=params["days"],
            compare=params["compare"],
            user=request.user if isinstance(request.user, User) else None,
        )
        serializer = WebAnalyticsRecapResponseSerializer(instance=recap, context=self.get_serializer_context())
        return Response(serializer.data)
