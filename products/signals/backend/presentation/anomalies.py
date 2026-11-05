import datetime
from typing import Any

from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import IntervalType

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import (
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
    is_mcp_request,
)
from posthog.dataclasses import frozen
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import APIScopePermission, is_service_auth
from posthog.ph_client import feature_enabled_or_false
from posthog.utils import relative_date_parse

from products.signals.backend.facade import api as signals_facade
from products.signals.backend.facade.api import (
    AnomalyDashboardNotFound,
    AnomalyGroupBy,
    AnomalyHistoryFilters,
    AnomalyInterval,
    AnomalySearchFilters,
)

ANOMALIES_SEARCH_FLAG = "anomalies-search"
READ_EVENT = "anomaly search read"
# Bounds the work of filling unscored buckets: an hourly series has 24 buckets a day.
MAX_RANGE = datetime.timedelta(days=366)


@frozen
class _DateRange:
    date_from: datetime.datetime
    date_to: datetime.datetime


class ProjectDateTimeField(serializers.DateTimeField):
    """Keeps the offset of the project timezone. The default field converts every value to UTC."""

    def to_representation(self, value: datetime.datetime) -> str:
        return value.isoformat()


class AnomalySearchQuerySerializer(serializers.Serializer):
    date_from = serializers.CharField(
        default="-7d",
        help_text="Earliest bucket start in the range. A relative date such as `-7d` or `-24h`, or an ISO 8601 date.",
    )
    date_to = serializers.CharField(
        required=False,
        help_text="Latest bucket start in the range. A relative date or an ISO 8601 date. Defaults to now.",
    )
    insight_id = serializers.IntegerField(required=False, help_text="Only the series of this insight, by numeric id.")
    dashboard_id = serializers.IntegerField(
        required=False, help_text="Only the series of the insights on this dashboard, by numeric id."
    )
    interval = serializers.ChoiceField(
        choices=AnomalyInterval.choices, required=False, help_text="Only series with this interval."
    )
    only_flagged = serializers.BooleanField(
        default=True,
        help_text="Only series, or insights, with at least one flagged bucket in the range. Set false to also list quiet ones.",
    )
    group_by = serializers.ChoiceField(
        choices=AnomalyGroupBy.choices,
        default=AnomalyGroupBy.SERIES,
        help_text="`series` returns one row per series in `series`. `insight` returns one row per insight in `insights`.",
    )
    limit = serializers.IntegerField(min_value=1, max_value=100, default=25, help_text="The most rows to return.")


class AnomalyInsightQuerySerializer(serializers.Serializer):
    insight_id = serializers.IntegerField(help_text="The insight, by numeric id.")
    series_key = serializers.CharField(
        required=False, help_text="Only this series, by the `series_key` of an anomaly search row."
    )
    date_from = serializers.CharField(
        default="-30d",
        help_text="Earliest bucket start in the range. A relative date such as `-30d`, or an ISO 8601 date.",
    )
    date_to = serializers.CharField(
        required=False,
        help_text="Latest bucket start in the range. A relative date or an ISO 8601 date. Defaults to now.",
    )
    include_buckets = serializers.BooleanField(
        default=True, help_text="Return the buckets of each series. Set false for the per-series summary only."
    )
    include_warmup = serializers.BooleanField(
        default=False,
        help_text="Include warm-up buckets: scored rows with a null score and flag, written while the detector "
        "still lacks history. When false, a warm-up bucket shows as `scored: false`.",
    )


class AnomalyFlaggedPointSerializer(serializers.Serializer):
    bucket_start = ProjectDateTimeField(help_text="The start of the flagged bucket, in the project timezone.")
    value = serializers.FloatField(allow_null=True, help_text="The series value of the bucket at scoring time.")
    score = serializers.FloatField(
        allow_null=True, help_text="The detector score of the bucket. Compare it only with buckets of the same series."
    )


class AnomalySeriesSerializer(serializers.Serializer):
    insight_id = serializers.IntegerField(source="summary.insight_id", help_text="The numeric id of the insight.")
    insight_name = serializers.CharField(
        source="insight.name", allow_null=True, help_text="The name of the insight. Null when it has none."
    )
    insight_url = serializers.CharField(
        help_text="Opens the insight with a date range around the flagged buckets of this series."
    )
    series_key = serializers.CharField(
        source="summary.series_key", help_text="Identifies the series. Pass it to anomaly insight history."
    )
    series_label = serializers.CharField(
        source="summary.series_label", allow_null=True, help_text="The series name as the insight shows it."
    )
    breakdown_value = serializers.CharField(
        source="summary.breakdown_value", allow_null=True, help_text="The breakdown value of the series, if any."
    )
    interval = serializers.ChoiceField(
        source="summary.interval", choices=AnomalyInterval.choices, help_text="The bucket interval of the series."
    )
    scored_buckets = serializers.IntegerField(
        source="summary.scored_buckets", help_text="Buckets in the range with a score. Warm-up buckets do not count."
    )
    flagged_buckets = serializers.IntegerField(
        source="summary.flagged_buckets", help_text="Scored buckets in the range that the detector flagged."
    )
    anomaly_rate = serializers.FloatField(
        source="summary.anomaly_rate", allow_null=True, help_text="`flagged_buckets / scored_buckets`."
    )
    expected_buckets = serializers.IntegerField(
        help_text="Completed buckets of the series interval in the range, scored or not."
    )
    coverage = serializers.FloatField(
        allow_null=True,
        help_text="`scored_buckets / expected_buckets`: how much of the range was scored. Unscored buckets are unknown, not quiet.",
    )
    scored_through = ProjectDateTimeField(
        source="summary.scored_through",
        allow_null=True,
        help_text="The newest scored bucket in the range. Buckets after it were not checked yet.",
    )
    baseline_rate = serializers.FloatField(
        source="summary.baseline_rate",
        allow_null=True,
        help_text="The anomaly rate over the 30 days before the range. Null when no bucket was scored then.",
    )
    first_flagged_bucket = ProjectDateTimeField(
        source="summary.first_flagged_bucket",
        allow_null=True,
        help_text="The oldest flagged bucket in the range, in the project timezone.",
    )
    last_flagged_bucket = ProjectDateTimeField(
        source="summary.last_flagged_bucket",
        allow_null=True,
        help_text="The newest flagged bucket in the range, in the project timezone.",
    )
    flagged_points = AnomalyFlaggedPointSerializer(
        many=True, help_text="Up to 5 flagged buckets in the range, newest first."
    )


class AnomalyTopSeriesSerializer(serializers.Serializer):
    series_key = serializers.CharField(help_text="Identifies the series.")
    series_label = serializers.CharField(allow_null=True, help_text="The series name as the insight shows it.")
    breakdown_value = serializers.CharField(allow_null=True, help_text="The breakdown value of the series, if any.")
    scored_buckets = serializers.IntegerField(help_text="Scored buckets of the series in the range.")
    flagged_buckets = serializers.IntegerField(help_text="Flagged buckets of the series in the range.")
    anomaly_rate = serializers.FloatField(allow_null=True, help_text="`flagged_buckets / scored_buckets`.")
    baseline_rate = serializers.FloatField(
        allow_null=True, help_text="The anomaly rate over the 30 days before the range."
    )


class AnomalyInsightRowSerializer(serializers.Serializer):
    insight_id = serializers.IntegerField(source="insight.id", help_text="The numeric id of the insight.")
    insight_name = serializers.CharField(
        source="insight.name", allow_null=True, help_text="The name of the insight. Null when it has none."
    )
    insight_url = serializers.CharField(help_text="Opens the insight with a date range around its flagged buckets.")
    series_count = serializers.IntegerField(
        source="rollup.series_count", help_text="Series of the insight scored in the range."
    )
    flagged_series = serializers.IntegerField(
        source="rollup.flagged_series", help_text="Series with at least one flagged bucket in the range."
    )
    scored_buckets = serializers.IntegerField(
        source="rollup.scored_buckets", help_text="Scored buckets, summed over the series."
    )
    flagged_buckets = serializers.IntegerField(
        source="rollup.flagged_buckets", help_text="Flagged buckets, summed over the series."
    )
    anomaly_rate = serializers.FloatField(
        source="rollup.anomaly_rate",
        allow_null=True,
        help_text="Summed `flagged_buckets / scored_buckets`. Never an average of series rates.",
    )
    last_flagged_bucket = ProjectDateTimeField(
        source="rollup.last_flagged_bucket", allow_null=True, help_text="The newest flagged bucket of any series."
    )
    top_series = AnomalyTopSeriesSerializer(many=True, help_text="Up to 3 flagged series, most anomalous first.")


class AnomalySearchResponseSerializer(serializers.Serializer):
    scoring_enabled = serializers.BooleanField(
        help_text=(
            "Whether anomaly scoring scores this project now. False when scoring does not cover the "
            "project, or when the project turned it off in its self-driving settings. Scores written "
            "before scoring was turned off are still returned."
        )
    )
    watched_insights = serializers.IntegerField(
        help_text=(
            "Active insights that scoring checks: saved trends insights that a person viewed, that sit on a "
            "dashboard someone opened, or that were edited in the active window (90 days by default), "
            "or that have an enabled alert or subscription."
        )
    )
    insights_scored_in_range = serializers.IntegerField(
        help_text="Insights with at least one scored bucket in the range. Results cover only these insights."
    )
    date_from = ProjectDateTimeField(help_text="The applied start of the range, in the project timezone.")
    date_to = ProjectDateTimeField(help_text="The applied end of the range, in the project timezone.")
    group_by = serializers.ChoiceField(choices=AnomalyGroupBy.choices, help_text="The applied grouping.")
    series = AnomalySeriesSerializer(
        many=True, help_text="One row per series, most anomalous first. Empty unless `group_by` is `series`."
    )
    insights = AnomalyInsightRowSerializer(
        many=True, help_text="One row per insight, most anomalous first. Empty unless `group_by` is `insight`."
    )
    truncated = serializers.BooleanField(help_text="True when `limit` or a read cap left rows out.")
    message = serializers.CharField(allow_null=True, help_text="Says why the result is empty. Null when it is not.")


class AnomalyBucketSerializer(serializers.Serializer):
    bucket_start = ProjectDateTimeField(help_text="The start of the bucket, in the project timezone.")
    scored = serializers.BooleanField(
        help_text="False for a completed bucket that has no score. Its value, score and flag are unknown, not 0."
    )
    value = serializers.FloatField(allow_null=True, help_text="The series value of the bucket at scoring time.")
    score = serializers.FloatField(
        allow_null=True, help_text="The detector score. Null on an unscored or warm-up bucket."
    )
    flag = serializers.BooleanField(
        allow_null=True, help_text="Whether the detector flagged the bucket. Null on an unscored or warm-up bucket."
    )
    scored_at = ProjectDateTimeField(allow_null=True, help_text="When the bucket was scored.")
    details = serializers.DictField(
        child=serializers.JSONField(),
        allow_null=True,
        help_text="Detector-specific values for the bucket. The keys depend on the detector.",
    )


class AnomalyInsightSeriesSerializer(serializers.Serializer):
    series_key = serializers.CharField(source="summary.series_key", help_text="Identifies the series.")
    series_label = serializers.CharField(
        source="summary.series_label", allow_null=True, help_text="The series name as the insight shows it."
    )
    breakdown_value = serializers.CharField(
        source="summary.breakdown_value", allow_null=True, help_text="The breakdown value of the series, if any."
    )
    scored_buckets = serializers.IntegerField(
        source="summary.scored_buckets", help_text="Buckets in the range with a score."
    )
    flagged_buckets = serializers.IntegerField(
        source="summary.flagged_buckets", help_text="Scored buckets in the range that the detector flagged."
    )
    anomaly_rate = serializers.FloatField(
        source="summary.anomaly_rate", allow_null=True, help_text="`flagged_buckets / scored_buckets`."
    )
    baseline_rate = serializers.FloatField(
        source="summary.baseline_rate",
        allow_null=True,
        help_text="The anomaly rate over the 30 days before the range. Null when no bucket was scored then.",
    )
    expected_buckets = serializers.IntegerField(help_text="Completed buckets in the range, scored or not.")
    coverage = serializers.FloatField(allow_null=True, help_text="`scored_buckets / expected_buckets`.")
    last_flagged_bucket = ProjectDateTimeField(
        source="summary.last_flagged_bucket", allow_null=True, help_text="The newest flagged bucket in the range."
    )
    buckets = AnomalyBucketSerializer(
        many=True, help_text="Oldest first, the newest result of each bucket. Empty when `include_buckets` is false."
    )


class AnomalyInsightResponseSerializer(serializers.Serializer):
    scoring_enabled = serializers.BooleanField(
        help_text=(
            "Whether anomaly scoring scores this project now. False when scoring does not cover the "
            "project, or when the project turned it off in its self-driving settings. Scores written "
            "before scoring was turned off are still returned."
        )
    )
    insight_id = serializers.IntegerField(source="insight.id", help_text="The numeric id of the insight.")
    insight_name = serializers.CharField(
        source="insight.name", allow_null=True, help_text="The name of the insight. Null when it has none."
    )
    insight_url = serializers.CharField(help_text="Opens the insight with a date range around its flagged buckets.")
    interval = serializers.ChoiceField(
        choices=AnomalyInterval.choices, allow_null=True, help_text="The bucket interval the scorer used."
    )
    profile = serializers.CharField(allow_null=True, help_text="The scoring profile.")
    detector = serializers.CharField(allow_null=True, help_text="The detector type, for example `zscore`.")
    detector_version = serializers.CharField(
        allow_null=True, help_text="A hash of the detector settings. It changes when the settings change."
    )
    series_count = serializers.IntegerField(source="rollup.series_count", help_text="Series scored in the range.")
    flagged_series = serializers.IntegerField(
        source="rollup.flagged_series", help_text="Series with at least one flagged bucket in the range."
    )
    scored_buckets = serializers.IntegerField(
        source="rollup.scored_buckets", help_text="Scored buckets, summed over the series."
    )
    flagged_buckets = serializers.IntegerField(
        source="rollup.flagged_buckets", help_text="Flagged buckets, summed over the series."
    )
    anomaly_rate = serializers.FloatField(
        source="rollup.anomaly_rate",
        allow_null=True,
        help_text="Summed `flagged_buckets / scored_buckets`. Never an average of series rates.",
    )
    date_from = ProjectDateTimeField(help_text="The applied start of the range, in the project timezone.")
    date_to = ProjectDateTimeField(help_text="The applied end of the range, in the project timezone.")
    series = AnomalyInsightSeriesSerializer(many=True, help_text="Every scored series, most anomalous first.")
    truncated = serializers.BooleanField(help_text="True when the cap of 2,000 buckets cut the history.")
    message = serializers.CharField(allow_null=True, help_text="Says why the result is empty. Null when it is not.")


class AnomalyViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Read-only anomaly rates of the saved trends insights that anomaly scoring checks."""

    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "insight"
    pagination_class = None

    def _user(self, request: Request) -> User:
        # The flag and insight access are both per user, so a request without a real user sees nothing.
        if is_service_auth(request) or not isinstance(request.user, User) or not self._enabled(request.user):
            raise NotFound()
        return request.user

    def _enabled(self, user: User) -> bool:
        organization_id = str(self.team.organization_id)
        return feature_enabled_or_false(
            ANOMALIES_SEARCH_FLAG,
            str(user.distinct_id),
            groups={"organization": organization_id, "project": str(self.team.uuid)},
            group_properties={
                "organization": {"id": organization_id},
                "project": {"id": self.team.id, "uuid": str(self.team.uuid)},
            },
        )

    def _date_range(self, query: dict[str, Any], now: datetime.datetime) -> _DateRange:
        timezone_info = self.team.timezone_info
        try:
            date_from = relative_date_parse(query["date_from"], timezone_info, now=now)
            date_to = relative_date_parse(query["date_to"], timezone_info, now=now) if query.get("date_to") else now
        except (ValueError, OverflowError):
            raise ValidationError({"date_from": "Use a relative date such as -7d, or an ISO 8601 date."})
        date_from, date_to = date_from.astimezone(timezone_info), date_to.astimezone(timezone_info)
        if date_from >= date_to:
            raise ValidationError({"date_from": "date_from must be before date_to."})
        if date_to - date_from > MAX_RANGE:
            raise ValidationError({"date_from": "The range can be at most 366 days."})
        return _DateRange(date_from=date_from, date_to=date_to)

    def _capture_read(self, request: Request, endpoint: str, **properties: Any) -> None:
        report_user_action(
            request.user,
            READ_EVENT,
            properties={"endpoint": endpoint, "via_mcp": is_mcp_request(request), **properties},
            team=self.team,
            request=request,
        )

    @validated_request(
        query_serializer=AnomalySearchQuerySerializer,
        responses={200: OpenApiResponse(response=AnomalySearchResponseSerializer)},
        summary="Search anomalous insight series",
    )
    @action(detail=False, methods=["GET"], required_scopes=["insight:read"])
    def search(self, request: ValidatedRequest, **kwargs: object) -> Response:
        user = self._user(request)
        query = request.validated_query_data
        now = timezone.now()
        date_range = self._date_range(query, now)
        filters = AnomalySearchFilters(
            date_from=date_range.date_from,
            date_to=date_range.date_to,
            insight_id=query.get("insight_id"),
            dashboard_id=query.get("dashboard_id"),
            interval=IntervalType(query["interval"]) if query.get("interval") else None,
            only_flagged=query["only_flagged"],
            group_by=AnomalyGroupBy(query["group_by"]),
            limit=query["limit"],
        )
        try:
            result = signals_facade.search_anomalies(team=self.team, user=user, filters=filters, now=now)
        except AnomalyDashboardNotFound:
            raise NotFound("Dashboard not found.")
        self._capture_read(
            request,
            "search",
            group_by=filters.group_by.value,
            scoring_enabled=result.scoring_enabled,
            rows=len(result.series) + len(result.insights),
            insights_scored_in_range=result.insights_scored_in_range,
        )
        return Response(
            AnomalySearchResponseSerializer(
                {
                    "scoring_enabled": result.scoring_enabled,
                    "watched_insights": result.watched_insights,
                    "insights_scored_in_range": result.insights_scored_in_range,
                    "date_from": date_range.date_from,
                    "date_to": date_range.date_to,
                    "group_by": filters.group_by,
                    "series": result.series,
                    "insights": result.insights,
                    "truncated": result.truncated,
                    "message": result.message,
                }
            ).data
        )

    @validated_request(
        query_serializer=AnomalyInsightQuerySerializer,
        responses={
            200: OpenApiResponse(response=AnomalyInsightResponseSerializer),
            404: OpenApiResponse(description="The insight does not exist or the user cannot read it."),
        },
        summary="Get the scored anomaly history of an insight",
    )
    @action(detail=False, methods=["GET"], required_scopes=["insight:read"])
    def insight(self, request: ValidatedRequest, **kwargs: object) -> Response:
        user = self._user(request)
        query = request.validated_query_data
        now = timezone.now()
        date_range = self._date_range(query, now)
        history = signals_facade.get_anomaly_insight_history(
            team=self.team,
            user=user,
            filters=AnomalyHistoryFilters(
                insight_id=query["insight_id"],
                date_from=date_range.date_from,
                date_to=date_range.date_to,
                series_key=query.get("series_key"),
                include_buckets=query["include_buckets"],
                include_warmup=query["include_warmup"],
            ),
            now=now,
        )
        if history is None:
            raise NotFound("Insight not found.")
        self._capture_read(
            request,
            "insight",
            scoring_enabled=history.scoring_enabled,
            series=len(history.series),
            flagged_series=history.rollup.flagged_series,
        )
        return Response(
            AnomalyInsightResponseSerializer(
                {
                    "scoring_enabled": history.scoring_enabled,
                    "insight": history.insight,
                    "insight_url": history.insight_url,
                    "interval": history.interval,
                    "profile": history.profile,
                    "detector": history.detector,
                    "detector_version": history.detector_version,
                    "rollup": history.rollup,
                    "date_from": date_range.date_from,
                    "date_to": date_range.date_to,
                    "series": history.series,
                    "truncated": history.truncated,
                    "message": history.message,
                }
            ).data
        )
