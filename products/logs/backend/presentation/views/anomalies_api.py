import hashlib
import datetime as dt
from typing import Any

from django.core.cache import cache

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.rate_limit import (
    LogsAnomalyScanBurstRateThrottle,
    LogsAnomalyScanSustainedRateThrottle,
    LogsSeriesBandsBurstRateThrottle,
    LogsSeriesBandsSustainedRateThrottle,
)

from products.logs.backend.anomaly_scan import MAX_EVAL_DAYS, ScanBudgetExceeded, floor_to_bucket, run_scan
from products.logs.backend.series_bands import (
    BASELINE_WEEKS,
    MIN_BASELINE_WEEKS_FOR_BAND,
    SeriesBandsFetchTruncated,
    run_series_bands,
)

SCAN_CACHE_TTL_SECONDS = 60
SERIES_BANDS_CACHE_TTL_SECONDS = 60

_STAGE_CHOICES = ["insufficient", "cold_start", "developing", "mature"]
_VERDICT_CHOICES = ["spike", "drop", "silence"]
_TIER_CHOICES = ["a", "b", "c", "d"]
_CONSTRAINT_CHOICES = ["team_retention", "byte_budget"]


class _ScanDateRangeSerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(
        help_text="Start of the evaluation window (ISO 8601). Buckets before this are only used as baseline history.",
    )
    date_to = serializers.DateTimeField(
        help_text="End of the evaluation window (ISO 8601), clamped to now.",
    )


class LogsAnomalyScanRequestSerializer(serializers.Serializer):
    serviceName = serializers.CharField(
        help_text=(
            "Service to scan (the log record's service_name). Required: the scan aggregates weeks of "
            "baseline history from raw logs, so it is scoped to one service per call."
        ),
    )
    dateRange = _ScanDateRangeSerializer(
        help_text=f"Evaluation window to scan for anomalies. May span at most {MAX_EVAL_DAYS} days.",
    )

    def validate_dateRange(self, value: dict[str, Any]) -> dict[str, Any]:
        if value["date_to"] <= value["date_from"]:
            raise serializers.ValidationError("date_to must be after date_from.")
        if value["date_to"] - value["date_from"] > dt.timedelta(days=MAX_EVAL_DAYS):
            raise serializers.ValidationError(f"The evaluation window may span at most {MAX_EVAL_DAYS} days.")
        return value


class LogsAnomalyScanBucketSerializer(serializers.Serializer):
    time = serializers.DateTimeField(help_text="Start of the 5 minute bucket (UTC).")
    observed = serializers.FloatField(help_text="Log records observed in this bucket.")
    expected = serializers.FloatField(
        allow_null=True,
        help_text="Expected count from the learned baseline. Null when the bucket was not scored.",
    )
    lower = serializers.FloatField(
        allow_null=True,
        help_text="Lower edge of the expected band. Observed below this is a drop or silence candidate.",
    )
    upper = serializers.FloatField(
        allow_null=True,
        help_text="Upper edge of the expected band. Observed above this is a spike candidate.",
    )
    stage = serializers.ChoiceField(
        choices=_STAGE_CHOICES,
        allow_null=True,
        help_text=(
            "How much history backed the baseline for this bucket. Wider bands and lower confidence in "
            "cold_start; mature means a full seasonal baseline. Null when the bucket was gated out "
            "(for example, traffic below the detection floor)."
        ),
    )
    verdict = serializers.ChoiceField(
        choices=_VERDICT_CHOICES,
        allow_null=True,
        help_text="Anomaly verdict for this bucket, or null when the observed count sat inside the band.",
    )


class LogsAnomalyScanSeriesSerializer(serializers.Serializer):
    severity = serializers.CharField(help_text="Severity level of this log series (for example info, warn, error).")
    stage = serializers.ChoiceField(
        choices=_STAGE_CHOICES,
        allow_null=True,
        help_text="Baseline stage reached by the end of the evaluation window. Null if no bucket was scored.",
    )
    tier = serializers.ChoiceField(
        choices=_TIER_CHOICES,
        allow_null=True,
        help_text=(
            "Traffic tier at the end of the window, from a (0.5 or more records per second) down to "
            "d (below the detection floor of roughly 1 record per minute)."
        ),
    )
    history_start = serializers.DateTimeField(
        allow_null=True,
        help_text="Earliest bucket with data inside the fetched lookback.",
    )
    limited_by = serializers.ChoiceField(
        choices=["series_history", *_CONSTRAINT_CHOICES],
        allow_null=True,
        help_text=(
            "What limited this series' baseline maturity, or null for a full baseline. series_history: "
            "data starts inside the lookback, because the series is young or a per-stream retention rule "
            "trimmed it (indistinguishable from the data). byte_budget and team_retention mirror the "
            "scan level constraints."
        ),
    )
    buckets = LogsAnomalyScanBucketSerializer(
        many=True,
        help_text="Per bucket observed counts and expected bands across the evaluation window, for evidence charts.",
    )


class LogsAnomalyScanIssueSerializer(serializers.Serializer):
    direction = serializers.ChoiceField(
        choices=["up", "down"],
        help_text="up covers spikes; down covers drops and silences (which share one issue per service).",
    )
    severity = serializers.CharField(
        allow_null=True,
        help_text="Severity of the spiking series. Null for down issues, which are tracked per service.",
    )
    kind = serializers.ChoiceField(
        choices=_VERDICT_CHOICES,
        help_text="Most severe verdict the issue reached. A drop that deepens into silence escalates in place.",
    )
    state = serializers.ChoiceField(
        choices=["pending", "active", "resolved"],
        help_text="Lifecycle state at the end of the evaluation window.",
    )
    opened_at = serializers.DateTimeField(help_text="Bucket where the issue first opened.")
    last_anomalous_at = serializers.DateTimeField(help_text="Most recent anomalous bucket attributed to this issue.")
    resolved_at = serializers.DateTimeField(
        allow_null=True,
        help_text="Bucket where the issue resolved, or null if it was still open at the end of the window.",
    )
    anomalous_bucket_times = serializers.ListField(
        child=serializers.DateTimeField(),
        help_text="Every anomalous bucket attributed to this issue, oldest first.",
    )


class LogsAnomalyScanResponseSerializer(serializers.Serializer):
    service_name = serializers.CharField(help_text="Service that was scanned.")
    eval_start = serializers.DateTimeField(help_text="Actual start of the evaluated window after any clipping.")
    eval_end = serializers.DateTimeField(help_text="Actual end of the evaluated window after clamping to now.")
    lookback_days = serializers.FloatField(help_text="Days of baseline history the scan used.")
    eval_clipped = serializers.BooleanField(
        help_text="True when the evaluation window was clipped to fit the read budget. The response covers only the clipped window.",
    )
    degraded = serializers.BooleanField(
        help_text="True when the scan could not afford the full lookback and fell back to a cheaper configuration.",
    )
    binding_constraints = serializers.ListField(
        child=serializers.ChoiceField(choices=_CONSTRAINT_CHOICES),
        help_text=(
            "Everything that limited the baseline, empty for an unconstrained scan. team_retention: the "
            "project's log retention is shorter than the full lookback. byte_budget: the scan degraded "
            "to stay inside its ClickHouse read budget."
        ),
    )
    series = LogsAnomalyScanSeriesSerializer(
        many=True,
        help_text="One entry per severity level observed for the service, with per bucket evidence.",
    )
    issues = LogsAnomalyScanIssueSerializer(
        many=True,
        help_text="Anomaly issues that opened during the evaluation window, oldest first.",
    )


class LogsAnomalyScanErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Human readable description of why the scan could not run.")


class LogsSeriesBandsRequestSerializer(serializers.Serializer):
    serviceName = serializers.CharField(
        help_text="Service whose per-series volume to chart (the log record's service_name).",
    )
    intervalMinutes = serializers.ChoiceField(
        choices=[60],
        default=60,
        help_text="Display grain in minutes for buckets and bands. Only hourly is supported today.",
    )


class LogsSeriesBandBucketSerializer(serializers.Serializer):
    time = serializers.DateTimeField(help_text="Start of the display bucket (UTC).")
    observed = serializers.IntegerField(help_text="Log count observed in this bucket.")
    lower = serializers.FloatField(
        allow_null=True,
        help_text="Lower edge of the expected band. Null while the series has too little history to band.",
    )
    upper = serializers.FloatField(
        allow_null=True,
        help_text="Upper edge of the expected band. Null while the series has too little history to band.",
    )


class LogsSeriesBandSeriesSerializer(serializers.Serializer):
    namespace = serializers.CharField(
        allow_blank=True, help_text="Namespace of the emitting resource; empty when the logs carry none."
    )
    environment = serializers.CharField(
        allow_blank=True, help_text="Deployment environment of the emitting resource; empty when the logs carry none."
    )
    severity = serializers.CharField(help_text="Lowercased log severity of this series (for example info, error).")
    total_count = serializers.IntegerField(
        help_text="Total observed log count over the window. Series are ordered by this, descending."
    )
    baseline_weeks = serializers.IntegerField(
        help_text=(
            f"Full weeks of history behind the band, 0 to {BASELINE_WEEKS}. "
            f"Below {MIN_BASELINE_WEEKS_FOR_BAND} the series is still learning and its buckets carry no band."
        )
    )
    buckets = LogsSeriesBandBucketSerializer(
        many=True,
        help_text="One entry per display bucket across the whole window, oldest first, zero-filled.",
    )


class LogsSeriesBandsResponseSerializer(serializers.Serializer):
    service_name = serializers.CharField(help_text="Service the series belong to.")
    window_start = serializers.DateTimeField(help_text="Start of the observed window (UTC, inclusive).")
    window_end = serializers.DateTimeField(help_text="End of the observed window (UTC, exclusive).")
    interval_minutes = serializers.IntegerField(help_text="Display grain of the buckets, in minutes.")
    series_truncated = serializers.BooleanField(
        help_text="True when the service has more series than the response carries; the quietest were dropped."
    )
    series = LogsSeriesBandSeriesSerializer(
        many=True,
        help_text="One entry per (namespace, environment, severity) series, ordered by observed volume descending.",
    )


class LogsSeriesBandsErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Human readable description of why the series could not be charted.")


class LogsAnomalyScanViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Anomaly surfaces over one service's log volume.

    Experimental, behind the logs-anomalies feature flag. `scan` computes
    everything per request from raw logs; `series_bands` reads the volume
    rollup. Neither persists anything.
    """

    scope_object = "logs"
    posthog_feature_flag = "logs-anomalies"
    permission_classes = [PostHogFeatureFlagPermission]
    throttle_classes = [LogsAnomalyScanBurstRateThrottle, LogsAnomalyScanSustainedRateThrottle]

    @validated_request(
        request_serializer=LogsAnomalyScanRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=LogsAnomalyScanResponseSerializer,
                description="Scan results: per severity evidence series and any issues that opened.",
            ),
            422: OpenApiResponse(
                response=LogsAnomalyScanErrorSerializer,
                description="The scan exceeded its read budget at every degradation step.",
            ),
        },
        summary="Scan a service's logs for volume anomalies",
        description=(
            "Runs anomaly detection on demand over one service's log volume for the given window. "
            "Learns per severity baselines from up to 6 weeks of history and returns per bucket "
            "expected bands plus any spike, drop, or silence issues. Synchronous and read only."
        ),
    )
    @action(detail=False, methods=["POST"], required_scopes=["logs:read"])
    def scan(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        data = request.validated_data
        service_name: str = data["serviceName"]
        eval_start = floor_to_bucket(data["dateRange"]["date_from"])
        eval_end = floor_to_bucket(min(data["dateRange"]["date_to"], dt.datetime.now(dt.UTC)))
        if eval_end <= eval_start:
            raise serializers.ValidationError("The evaluation window is empty after clamping to now.")

        cache_key = (
            "logs_anomaly_scan/"
            + hashlib.sha256(
                f"{self.team.id}/{service_name}/{eval_start.isoformat()}/{eval_end.isoformat()}".encode()
            ).hexdigest()
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            result = run_scan(self.team, service_name, eval_start, eval_end)
        except ScanBudgetExceeded as err:
            return Response({"error": str(err)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        response_data = LogsAnomalyScanResponseSerializer(result).data
        cache.set(cache_key, response_data, SCAN_CACHE_TTL_SECONDS)
        return Response(response_data)

    @validated_request(
        request_serializer=LogsSeriesBandsRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=LogsSeriesBandsResponseSerializer,
                description="Observed volume and expected band per series of the service.",
            ),
            422: OpenApiResponse(
                response=LogsSeriesBandsErrorSerializer,
                description="The service has too many series to chart in one response.",
            ),
        },
        summary="Per-series log volume with expected bands",
        description=(
            "Returns the last 7 days of log volume for every (namespace, environment, severity) series "
            "of one service, with a time-of-week expected band derived from the prior weeks of the "
            "volume rollup. Synchronous and read only."
        ),
    )
    @action(
        detail=False,
        methods=["POST"],
        required_scopes=["logs:read"],
        url_path="series_bands",
        throttle_classes=[LogsSeriesBandsBurstRateThrottle, LogsSeriesBandsSustainedRateThrottle],
    )
    def series_bands(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        data = request.validated_data
        service_name: str = data["serviceName"]
        interval_minutes: int = int(data["intervalMinutes"])

        cache_key = (
            "logs_series_bands/"
            + hashlib.sha256(f"{self.team.id}/{service_name}/{interval_minutes}".encode()).hexdigest()
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            result = run_series_bands(self.team, service_name, interval_minutes=interval_minutes)
        except SeriesBandsFetchTruncated as err:
            return Response({"error": str(err)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        response_data = LogsSeriesBandsResponseSerializer(result).data
        cache.set(cache_key, response_data, SERIES_BANDS_CACHE_TTL_SECONDS)
        return Response(response_data)
