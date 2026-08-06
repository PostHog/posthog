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
from posthog.rate_limit import LogsAnomalyScanBurstRateThrottle, LogsAnomalyScanSustainedRateThrottle

from products.logs.backend.anomaly_scan import (
    BUCKETS_PER_DAY,
    MAX_EVAL_DAYS,
    ScanBudgetExceeded,
    ScanResult,
    floor_to_bucket,
    run_scan,
)

SCAN_CACHE_TTL_SECONDS = 60

_STAGE_CHOICES = ["insufficient", "cold_start", "developing", "mature"]
_VERDICT_CHOICES = ["spike", "drop", "silence"]
_TIER_CHOICES = ["a", "b", "c", "d"]


class LogsAnomalyScanRequestSerializer(serializers.Serializer):
    serviceName = serializers.CharField(
        help_text=(
            "Service to scan (the log record's service_name). Required: the scan aggregates weeks of "
            "baseline history from raw logs, so it is scoped to one service per call."
        ),
    )
    dateFrom = serializers.DateTimeField(
        help_text="Start of the evaluation window (ISO 8601). Buckets before this are only used as baseline history.",
    )
    dateTo = serializers.DateTimeField(
        help_text=(
            "End of the evaluation window (ISO 8601), clamped to now. The window may span at most "
            f"{MAX_EVAL_DAYS} days."
        ),
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["dateTo"] <= attrs["dateFrom"]:
            raise serializers.ValidationError("dateTo must be after dateFrom.")
        if attrs["dateTo"] - attrs["dateFrom"] > dt.timedelta(days=MAX_EVAL_DAYS):
            raise serializers.ValidationError(f"The evaluation window may span at most {MAX_EVAL_DAYS} days.")
        return attrs


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
    historyStart = serializers.DateTimeField(
        allow_null=True,
        help_text=(
            "Earliest bucket with data inside the fetched lookback. When this is later than the lookback "
            "start, the series is younger than the lookback or older data has been dropped by a "
            "retention rule."
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
    openedAt = serializers.DateTimeField(help_text="Bucket where the issue first opened.")
    lastAnomalousAt = serializers.DateTimeField(help_text="Most recent anomalous bucket attributed to this issue.")
    resolvedAt = serializers.DateTimeField(
        allow_null=True,
        help_text="Bucket where the issue resolved, or null if it was still open at the end of the window.",
    )
    anomalousBucketTimes = serializers.ListField(
        child=serializers.DateTimeField(),
        help_text="Every anomalous bucket attributed to this issue, oldest first.",
    )


class LogsAnomalyScanResponseSerializer(serializers.Serializer):
    serviceName = serializers.CharField(help_text="Service that was scanned.")
    evalStart = serializers.DateTimeField(help_text="Actual start of the evaluated window after any clipping.")
    evalEnd = serializers.DateTimeField(help_text="Actual end of the evaluated window after clamping to now.")
    lookbackDays = serializers.FloatField(help_text="Days of baseline history the scan used.")
    evalClipped = serializers.BooleanField(
        help_text="True when the evaluation window was clipped to fit the read budget. The response covers only the clipped window.",
    )
    degraded = serializers.BooleanField(
        help_text="True when the scan could not afford the full lookback and fell back to a cheaper configuration.",
    )
    bindingConstraint = serializers.ChoiceField(
        choices=["none", "team_retention", "byte_budget"],
        help_text=(
            "What limited the baseline. team_retention: the project's log retention is shorter than the "
            "full lookback. byte_budget: the scan degraded to stay inside its ClickHouse read budget."
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


def _result_payload(result: ScanResult) -> dict[str, Any]:
    return {
        "serviceName": result.service_name,
        "evalStart": result.eval_start,
        "evalEnd": result.eval_end,
        "lookbackDays": result.lookback_buckets / BUCKETS_PER_DAY,
        "evalClipped": result.eval_clipped,
        "degraded": result.degraded,
        "bindingConstraint": result.binding_constraint,
        "series": [
            {
                "severity": series.severity,
                "stage": series.stage,
                "tier": series.tier,
                "historyStart": series.history_start,
                "buckets": [
                    {
                        "time": bucket.time,
                        "observed": bucket.observed,
                        "expected": bucket.expected,
                        "lower": bucket.lower,
                        "upper": bucket.upper,
                        "stage": bucket.stage,
                        "verdict": bucket.verdict,
                    }
                    for bucket in series.buckets
                ],
            }
            for series in result.series
        ],
        "issues": [
            {
                "direction": issue.direction,
                "severity": issue.severity,
                "kind": issue.kind,
                "state": issue.state,
                "openedAt": issue.opened_at,
                "lastAnomalousAt": issue.last_anomalous_at,
                "resolvedAt": issue.resolved_at,
                "anomalousBucketTimes": issue.anomalous_bucket_times,
            }
            for issue in result.issues
        ],
    }


class LogsAnomalyScanViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """On-demand anomaly scan over one service's log volume.

    Experimental, behind the logs-anomalies feature flag. Computes everything
    per request from raw logs; nothing is persisted.
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
            422: OpenApiResponse(description="The scan exceeded its read budget at every degradation step."),
        },
        summary="Scan a service's logs for volume anomalies",
        description=(
            "Runs anomaly detection on demand over one service's log volume for the given window. "
            "Learns per severity baselines from up to 6 weeks of history and returns per bucket "
            "expected bands plus any spike, drop, or silence issues. Synchronous and read only."
        ),
    )
    @action(detail=False, methods=["POST"])
    def scan(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        data = request.validated_data
        service_name: str = data["serviceName"]
        eval_start = floor_to_bucket(data["dateFrom"])
        eval_end = floor_to_bucket(min(data["dateTo"], dt.datetime.now(dt.UTC)))
        if eval_end <= eval_start:
            return Response(
                {"error": "The evaluation window is empty after clamping to now."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

        payload = _result_payload(result)
        response_serializer = LogsAnomalyScanResponseSerializer(payload)
        response_data = response_serializer.data
        cache.set(cache_key, response_data, SCAN_CACHE_TTL_SECONDS)
        return Response(response_data)
