from typing import Any, cast

from django.db import models

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import DateRange

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.event_usage import report_user_action
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from products.logs.backend.facade.api import (
    NaturalLanguageQueryFailed,
    NaturalLanguageQueryUnavailable,
    is_valid_date,
    translate_natural_language_query,
)

LOGS_NATURAL_LANGUAGE_SEARCH_FLAG = "logs-natural-language-search"


class LogsNaturalLanguageFilterType(models.TextChoices):
    LOG = "log"
    LOG_ATTRIBUTE = "log_attribute"
    LOG_RESOURCE_ATTRIBUTE = "log_resource_attribute"


class _LogsNaturalLanguageDateRangeSerializer(serializers.Serializer):
    date_from = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Start of the date range. Accepts ISO 8601 timestamps or relative formats such as -1h or -7d.",
    )
    date_to = serializers.CharField(
        required=False,
        allow_null=True,
        help_text='End of the date range. Same format as date_from. Null means "now".',
    )

    # The date parser turns an unreadable value into "now" without an error, which would silently
    # scope the service and attribute lists to the wrong window.
    @staticmethod
    def _check_date(value: str | None, *, allow_all: bool = False) -> str | None:
        if not is_valid_date(value, allow_all=allow_all):
            raise serializers.ValidationError("Use an ISO 8601 timestamp or a relative date such as -1h or -7d.")
        return value

    def validate_date_from(self, value: str | None) -> str | None:
        return self._check_date(value, allow_all=True)

    def validate_date_to(self, value: str | None) -> str | None:
        return self._check_date(value)


class LogsNaturalLanguageQueryRequestSerializer(serializers.Serializer):
    query = serializers.CharField(
        max_length=500,
        trim_whitespace=True,
        help_text="The plain-language request, for example 'error logs from checkout in the last 2 hours'.",
    )
    dateRange = _LogsNaturalLanguageDateRangeSerializer(
        required=False,
        help_text="The viewer's current date range. Used when the request names no time, and to scope the "
        "service and attribute lists the model may choose from.",
    )


class _LogsNaturalLanguageCandidateFilterSerializer(serializers.Serializer):
    key = serializers.CharField(help_text='Attribute key, or "message" for the log body text.')
    type = serializers.ChoiceField(
        choices=LogsNaturalLanguageFilterType.choices,
        help_text='"log" filters the log body. "log_attribute" and "log_resource_attribute" filter attributes.',
    )
    operator = serializers.CharField(help_text="Property operator, for example exact, icontains or is_set.")
    value = serializers.JSONField(
        required=False,
        help_text="A list of strings for exact and is_not, a string for text operators, absent for is_set.",
    )


class _LogsNaturalLanguageCandidateQuerySerializer(serializers.Serializer):
    dateRange = _LogsNaturalLanguageDateRangeSerializer(help_text="Date range of this reading.")
    severityLevels = serializers.ListField(
        child=serializers.ChoiceField(choices=["trace", "debug", "info", "warn", "error", "fatal"]),
        help_text="Severity levels to keep. Empty means all levels.",
    )
    serviceNames = serializers.ListField(
        child=serializers.CharField(), help_text="Services to keep. Empty means all services."
    )
    filterGroup = serializers.ListField(
        child=_LogsNaturalLanguageCandidateFilterSerializer(),
        help_text="Attribute and message filters, combined with AND.",
    )


class _LogsNaturalLanguageCandidateSerializer(serializers.Serializer):
    label = serializers.CharField(  # type: ignore[assignment]
        help_text="Short plain-language summary of this reading of the request."
    )
    query = _LogsNaturalLanguageCandidateQuerySerializer(help_text="Viewer filters for this reading.")
    probability = serializers.FloatField(
        allow_null=True, help_text="How likely the decision model thinks this reading is. Null when not ranked."
    )


class LogsNaturalLanguageQueryResponseSerializer(serializers.Serializer):
    candidates = serializers.ListField(
        child=_LogsNaturalLanguageCandidateSerializer(), help_text="Readings of the request, best first. Can be empty."
    )
    confidence = serializers.FloatField(
        allow_null=True,
        help_text="The first candidate's probability from the decision model. Null when it did not rank them.",
    )
    ranked_by = serializers.ChoiceField(
        choices=["decision_model", "proposal_order"],
        help_text="decision_model when Jev ranked the candidates, proposal_order when it was skipped.",
    )
    dropped_count = serializers.IntegerField(
        help_text="Proposed readings dropped because they named a service or attribute key the project lacks."
    )


class _LogsNaturalLanguageErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="What went wrong.")


class LogsNaturalLanguageQueryViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "logs"
    posthog_feature_flag = LOGS_NATURAL_LANGUAGE_SEARCH_FLAG
    permission_classes = [PostHogFeatureFlagPermission]
    throttle_classes = [AIBurstRateThrottle, AISustainedRateThrottle]
    serializer_class = LogsNaturalLanguageQueryRequestSerializer

    @extend_schema(
        request=LogsNaturalLanguageQueryRequestSerializer,
        responses={
            200: LogsNaturalLanguageQueryResponseSerializer,
            502: OpenApiResponse(response=_LogsNaturalLanguageErrorSerializer),
            503: OpenApiResponse(response=_LogsNaturalLanguageErrorSerializer),
        },
        description=(
            "Turn a plain-language request into ranked log viewer filter candidates. Nothing is persisted. "
            "Only the request text, service names and attribute keys are sent to the models."
        ),
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not self.organization.is_ai_data_processing_approved:
            raise PermissionDenied("AI data processing must be approved by your organization to search with AI")
        tag_queries(product=Product.LOGS, feature=Feature.QUERY)
        serializer = LogsNaturalLanguageQueryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        date_range_data = serializer.validated_data.get("dateRange") or {}
        date_range = DateRange(
            date_from=date_range_data.get("date_from") or "-1h", date_to=date_range_data.get("date_to")
        )
        user = cast(User, request.user)

        try:
            result = translate_natural_language_query(
                self.team, serializer.validated_data["query"], date_range, distinct_id=str(user.distinct_id)
            )
        except NaturalLanguageQueryUnavailable:
            return Response(
                {"error": "AI search is not available on this instance."}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except NaturalLanguageQueryFailed:
            return Response(
                {"error": "AI search could not read that request. Try again or rephrase it."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        report_user_action(
            user,
            "logs natural language query translated",
            {
                "candidate_count": len(result.candidates),
                "dropped_count": result.dropped_count,
                "ranked_by": result.ranked_by,
                "confidence": result.confidence,
            },
            team=self.team,
            request=request,
        )
        return Response(LogsNaturalLanguageQueryResponseSerializer(instance=result).data, status=status.HTTP_200_OK)
