from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.rate_limit import LlmsTxtFetchBurstRateThrottle, LlmsTxtFetchSustainedRateThrottle

from products.web_analytics.backend.llms_txt import LlmsTxtFetchError, fetch_llms_txt
from products.web_analytics.backend.recap import build_team_recap
from products.web_analytics.backend.serializers import (
    LlmsTxtFetchRequestSerializer,
    LlmsTxtFetchResponseSerializer,
    WebAnalyticsRecapResponseSerializer,
    WeeklyDigestResponseSerializer,
)
from products.web_analytics.backend.weekly_digest import DigestDataUnavailableError, build_team_digest

MIN_DAYS = 1
MAX_DAYS = 90
DEFAULT_DAYS = 7


class WebAnalyticsDigestUnavailable(APIException):
    # ClickHouse rejects the digest's queries when it is at capacity. Reporting that as a 200 full of
    # zeros makes an active project look like it has no traffic, and the caller has no way to tell.
    # A stable code lets clients retry instead of believing the zero.
    status_code = 503
    default_detail = "Couldn't load your web analytics right now. Try again, and if it keeps happening contact support."
    default_code = "web_analytics_digest_unavailable"


class _DigestQuerySerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=MIN_DAYS, max_value=MAX_DAYS, required=False, default=DEFAULT_DAYS)
    compare = serializers.BooleanField(required=False, default=True)


class WebAnalyticsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "web_analytics"
    scope_object_read_actions = ["weekly_digest", "recap", "llms_txt"]
    serializer_class = WeeklyDigestResponseSerializer

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action == "llms_txt":
            # One outbound fetch of a caller-supplied file per call, blocking a web worker while it runs.
            return [LlmsTxtFetchBurstRateThrottle(), LlmsTxtFetchSustainedRateThrottle()]
        return super().get_throttles()

    @validated_request(
        request_serializer=LlmsTxtFetchRequestSerializer,
        operation_id="web_analytics_fetch_llms_txt",
        summary="Load an llms.txt file",
        description="Loads an llms.txt file from a public URL for coverage analysis without saving it.",
        responses={
            200: OpenApiResponse(response=LlmsTxtFetchResponseSerializer),
            400: OpenApiResponse(description="The URL is invalid, inaccessible, or does not return an llms.txt file."),
        },
        tags=["web_analytics"],
    )
    @action(detail=False, methods=["post"], url_path="llms_txt")
    def llms_txt(self, request: ValidatedRequest, **kwargs: object) -> Response:
        try:
            fetched_file = fetch_llms_txt(request.validated_data["url"])
        except LlmsTxtFetchError as error:
            raise exceptions.ValidationError({"url": str(error)}) from error
        return Response(LlmsTxtFetchResponseSerializer(instance=fetched_file).data)

    @extend_schema(
        operation_id="web_analytics_weekly_digest",
        summary="Summarize web analytics",
        description=(
            "Summarizes a project's web analytics over a lookback window (default 7 days): unique "
            "visitors, pageviews, sessions, bounce rate, and average session duration with "
            "period-over-period comparisons, plus the top 5 pages, top 5 traffic sources, and "
            "goal conversions. Always excludes internal and test users. Fails with a 503 when the "
            "underlying queries cannot run, so a zero total always means the project had no traffic."
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
        responses={
            200: OpenApiResponse(response=WeeklyDigestResponseSerializer),
            503: OpenApiResponse(description="The web analytics data could not be loaded. Retry the request."),
        },
        tags=["web_analytics"],
    )
    @action(detail=False, methods=["get"], url_path="weekly_digest")
    def weekly_digest(self, request: "Request", **kwargs: object) -> Response:
        query_serializer = _DigestQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data
        try:
            digest = build_team_digest(
                self.team,
                days=params["days"],
                compare=params["compare"],
                user=request.user if isinstance(request.user, User) else None,
            )
        except DigestDataUnavailableError as error:
            raise WebAnalyticsDigestUnavailable() from error
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
        responses={
            200: OpenApiResponse(response=WebAnalyticsRecapResponseSerializer),
            503: OpenApiResponse(description="The web analytics data could not be loaded. Retry the request."),
        },
        tags=["web_analytics"],
    )
    @action(detail=False, methods=["get"], url_path="recap")
    def recap(self, request: "Request", **kwargs: object) -> Response:
        query_serializer = _DigestQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data
        try:
            recap = build_team_recap(
                self.team,
                days=params["days"],
                compare=params["compare"],
                user=request.user if isinstance(request.user, User) else None,
            )
        except DigestDataUnavailableError as error:
            raise WebAnalyticsDigestUnavailable() from error
        serializer = WebAnalyticsRecapResponseSerializer(instance=recap, context=self.get_serializer_context())
        return Response(serializer.data)
