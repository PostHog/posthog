from typing import cast

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ActionConversionGoal, CustomEventConversionGoal, DateRange

from posthog.api.documentation import PropertyItemSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from products.web_analytics.backend.ai_summary import (
    MODEL_ID,
    cache_summary,
    cache_ttl_for,
    compute_cache_key,
    generate_web_analytics_summary,
    get_cached_summary,
)
from products.web_analytics.backend.serializers import WeeklyDigestResponseSerializer
from products.web_analytics.backend.weekly_digest import DigestFilterSpec, build_digest_from_spec, build_team_digest

MIN_DAYS = 1
MAX_DAYS = 90
DEFAULT_DAYS = 7

logger = structlog.get_logger(__name__)


class _DigestQuerySerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=MIN_DAYS, max_value=MAX_DAYS, required=False, default=DEFAULT_DAYS)
    compare = serializers.BooleanField(required=False, default=True)


@extend_schema_field(
    {
        "type": "object",
        "description": (
            "Conversion goal. Either {actionId: number} for an action goal "
            "or {customEventName: string} for a custom event goal."
        ),
        "properties": {
            "actionId": {"type": "integer", "description": "ID of the action used as conversion goal."},
            "customEventName": {"type": "string", "description": "Custom event name used as conversion goal."},
        },
        "additionalProperties": True,
    }
)
class _ConversionGoalField(serializers.DictField):
    pass


class AISummaryFilterSpecSerializer(serializers.Serializer):
    date_from = serializers.CharField(
        help_text="Start of the analysis window. Accepts a relative spec like '-7d' or an ISO date like '2026-01-01'."
    )
    date_to = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="End of the analysis window. Accepts the same formats as date_from, or null for an open-ended range up to now.",
    )
    compare = serializers.BooleanField(
        required=False,
        default=True,
        help_text="When true, include period-over-period change for each metric against the prior equal-length period.",
    )
    properties = PropertyItemSerializer(
        many=True,
        required=False,
        default=list,
        help_text="Property filters applied to all underlying queries.",
    )
    conversion_goal = _ConversionGoalField(
        required=False,
        allow_null=True,
        help_text="Optional conversion goal — either ActionConversionGoal ({actionId}) or CustomEventConversionGoal ({customEventName}).",
    )
    filter_test_accounts = serializers.BooleanField(
        required=False, default=True, help_text="Whether to exclude internal/test-account events from the analysis."
    )
    do_path_cleaning = serializers.BooleanField(
        required=False,
        default=False,
        help_text="When true, apply the team's path-cleaning rules before bucketing by page path.",
    )


class AISummaryResponseSerializer(serializers.Serializer):
    summary_text = serializers.CharField(help_text="LLM-generated plain-text summary, up to ~150 words.")
    created_at = serializers.DateTimeField(help_text="When the summary was generated.")
    model_id = serializers.CharField(help_text="LLM model identifier used to generate this summary.")
    cached = serializers.BooleanField(
        help_text="True when this summary was reused from the cache; false when freshly generated."
    )


def _spec_from_validated(data: dict) -> DigestFilterSpec:
    conversion_goal: ActionConversionGoal | CustomEventConversionGoal | None = None
    raw_goal = data.get("conversion_goal")
    if raw_goal:
        if "actionId" in raw_goal:
            conversion_goal = ActionConversionGoal(actionId=raw_goal["actionId"])
        elif "customEventName" in raw_goal:
            conversion_goal = CustomEventConversionGoal(customEventName=raw_goal["customEventName"])
    return DigestFilterSpec(
        date_range=DateRange(date_from=data["date_from"], date_to=data.get("date_to") or None),
        compare=data.get("compare", True),
        properties=list(data.get("properties") or []),
        conversion_goal=conversion_goal,
        filter_test_accounts=data.get("filter_test_accounts", True),
        do_path_cleaning=data.get("do_path_cleaning", False),
    )


def _is_check_request(request: "Request") -> bool:
    return request.query_params.get("check", "").lower() in ("1", "true", "yes")


class _AISummaryGenerationFailed(exceptions.APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Failed to generate AI summary. Please try again."
    default_code = "ai_summary_failed"


class WebAnalyticsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "web_analytics"
    scope_object_read_actions = ["weekly_digest"]
    scope_object_write_actions = ["ai_summary"]
    serializer_class = WeeklyDigestResponseSerializer

    def get_throttles(self):
        if self.action == "ai_summary" and not _is_check_request(self.request):
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        return super().get_throttles()

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
        digest = build_team_digest(self.team, days=params["days"], compare=params["compare"])
        serializer = self.get_serializer(instance=digest)
        return Response(serializer.data)

    @extend_schema(
        operation_id="web_analytics_ai_summary",
        summary="Generate AI summary of web analytics",
        description=(
            "Returns an AI summary of the team's web analytics for the supplied filter spec. "
            "If a fresh summary is cached it is returned as-is. Otherwise, when check=true the call returns "
            "HTTP 204 without invoking the LLM; when check is omitted/false the LLM is invoked, the result "
            "is cached, and returned. The generate path is rate-limited per user."
        ),
        request=AISummaryFilterSpecSerializer,
        parameters=[
            OpenApiParameter(
                name="check",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                default=False,
                description=(
                    "When true, only return a cached summary if one is fresh (HTTP 204 on a miss) and never "
                    "invoke the LLM. Used by the dashboard to hydrate a cached summary without incurring cost."
                ),
            ),
        ],
        responses={
            200: OpenApiResponse(response=AISummaryResponseSerializer),
            204: OpenApiResponse(description="check=true and no fresh cached summary exists for this filter spec."),
            502: OpenApiResponse(description="LLM call failed."),
        },
        tags=["web_analytics"],
    )
    @action(detail=False, methods=["post"], url_path="ai_summary")
    def ai_summary(self, request: "Request", **kwargs: object) -> Response:
        serializer = AISummaryFilterSpecSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        spec = _spec_from_validated(serializer.validated_data)
        cache_key, normalized = compute_cache_key(spec, team=self.team)

        cached = get_cached_summary(cache_key)
        if cached is not None:
            return Response({**cached, "cached": True})

        if _is_check_request(request):
            return Response(status=status.HTTP_204_NO_CONTENT)

        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()
        user = cast(User, request.user)

        digest = build_digest_from_spec(self.team, spec, include_context_events=True)

        try:
            summary_text = generate_web_analytics_summary(
                team=self.team,
                normalized_spec=normalized,
                digest=digest,
                user=user,
            )
        except Exception:
            logger.exception("web_analytics_ai_summary_failed", team_id=self.team.pk, model_id=MODEL_ID)
            raise _AISummaryGenerationFailed()

        ttl = cache_ttl_for(spec, team=self.team)
        payload = cache_summary(cache_key, summary_text=summary_text, ttl=ttl)
        return Response({**payload, "cached": False})
