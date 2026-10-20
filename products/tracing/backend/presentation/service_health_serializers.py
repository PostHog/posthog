import datetime as dt
from zoneinfo import ZoneInfo

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.utils import relative_date_parse

from ..facade.contracts import ServiceHealthParams
from ..facade.enums import (
    ServiceHealthBaseline,
    ServiceHealthCompare,
    ServiceHealthOrderBy,
    ServiceHealthSpanScope,
    ServiceHealthStatus,
)
from .date_window import normalize_tracing_window

UTC = ZoneInfo("UTC")


class _ServiceHealthDateRangeSerializer(serializers.Serializer):
    date_from = serializers.CharField(
        required=False, allow_null=True, help_text="Relative (-30m, -6h, -7d) or ISO 8601."
    )
    date_to = serializers.CharField(required=False, allow_null=True, help_text='Same format. Omit or null for "now".')


class _ServiceHealthQuerySerializer(serializers.Serializer):
    dateRange = _ServiceHealthDateRangeSerializer(
        required=False, help_text="The window to score. Defaults to the last hour."
    )
    compare = serializers.ChoiceField(
        choices=ServiceHealthBaseline.choices,
        default=ServiceHealthBaseline.PREVIOUS_PERIOD,
        help_text=(
            "The baseline. previous_period (default) is the same length just before the window. previous_day and "
            "previous_week shift the window back 1 or 7 days. none skips it. baselineDateRange overrides it."
        ),
    )
    environment = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Only this environment, matched without case on deployment.environment.name, then deployment.environment, then env.",
    )
    serviceNames = serializers.ListField(
        child=serializers.CharField(), required=False, default=list, max_length=100, help_text="Only these services."
    )
    spanScope = serializers.ChoiceField(
        choices=ServiceHealthSpanScope.choices,
        default=ServiceHealthSpanScope.ENTRY,
        help_text="entry (default) counts root, server and consumer spans, one per request. all counts every span.",
    )
    orderBy = serializers.ChoiceField(
        choices=ServiceHealthOrderBy.choices,
        default=ServiceHealthOrderBy.STATUS,
        help_text="status (default) puts silent, regressed and degraded first. The others sort high to low.",
    )
    limit = serializers.IntegerField(default=25, min_value=1, max_value=200, help_text="Max service rows, 1-200.")


class ServiceHealthRequestSerializer(serializers.Serializer):
    query = _ServiceHealthQuerySerializer(help_text="The service health query. Every field is optional.")
    baselineDateRange = _ServiceHealthDateRangeSerializer(
        required=False, help_text="An explicit baseline window. Overrides query.compare."
    )

    def validate(self, attrs: dict) -> dict:
        for name, window in (
            ("dateRange", attrs["query"].get("dateRange")),
            ("baselineDateRange", attrs.get("baselineDateRange")),
        ):
            if window is None:
                continue
            start = normalize_tracing_window(window.get("date_from")) or "-1h"
            end = normalize_tracing_window(window.get("date_to"))
            if relative_date_parse(start, UTC) >= (relative_date_parse(end, UTC) if end else dt.datetime.now(UTC)):
                raise serializers.ValidationError({name: "date_from must be before date_to."})
        return attrs


def service_health_params(validated_data: dict) -> ServiceHealthParams:
    data = validated_data["query"]
    date_range = data.get("dateRange") or {}
    baseline = validated_data.get("baselineDateRange")
    compare = ServiceHealthCompare.CUSTOM if baseline else ServiceHealthCompare(data["compare"])
    compare_from, compare_to = (baseline.get("date_from"), baseline.get("date_to")) if baseline else (None, None)
    return ServiceHealthParams(
        date_from=normalize_tracing_window(date_range.get("date_from")) or "-1h",
        date_to=normalize_tracing_window(date_range.get("date_to")),
        compare=compare,
        compare_date_from=normalize_tracing_window(compare_from),
        compare_date_to=normalize_tracing_window(compare_to),
        environment=(data.get("environment") or "").strip() or None,
        service_names=tuple(data["serviceNames"]),
        span_scope=ServiceHealthSpanScope(data["spanScope"]),
        order_by=ServiceHealthOrderBy(data["orderBy"]),
        limit=data["limit"],
    )


class _ServiceHealthTimeRangeSerializer(serializers.Serializer):
    date_from = serializers.CharField(help_text="Start, ISO 8601 UTC, inclusive.")
    date_to = serializers.CharField(help_text="End, ISO 8601 UTC, exclusive.")


class _ServiceHealthWindowSerializer(serializers.Serializer):
    current = _ServiceHealthTimeRangeSerializer(
        help_text="The scored window. Reuse it as dateRange in follow-up calls."
    )
    baseline = _ServiceHealthTimeRangeSerializer(
        allow_null=True, help_text="The baseline window. Null when compare is none."
    )
    timezone = serializers.CharField(help_text="Always UTC.")


class _ServiceHealthSummarySerializer(serializers.Serializer):
    services = serializers.IntegerField(help_text="Services scored, before the limit.")
    requests = serializers.IntegerField(help_text="Requests over all scored services.")
    ok = serializers.IntegerField(help_text="Services per status.")
    degraded = serializers.IntegerField(help_text="Services per status.")
    regressed = serializers.IntegerField(help_text="Services per status.")
    silent = serializers.IntegerField(help_text="Services per status.")
    new = serializers.IntegerField(help_text="Services per status.")
    recovered = serializers.IntegerField(help_text="Services per status.")
    improved = serializers.IntegerField(help_text="Services per status.")


class _ServiceHealthRowSerializer(serializers.Serializer):
    service = serializers.CharField(help_text="Service name.")
    status = serializers.ChoiceField(
        choices=ServiceHealthStatus.choices,
        help_text=(
            "silent: spans stopped. regressed: error rate or p95 worse than the baseline. degraded: error rate 5% or "
            "more. new: no spans in the baseline. recovered, improved: the reverse of regressed."
        ),
    )
    reason = serializers.CharField(allow_blank=True, help_text="Why the service has this status. Empty for ok.")
    requests = serializers.IntegerField(help_text="Spans in the window, in the chosen spanScope.")
    throughput_per_min = serializers.FloatField(help_text="Requests per minute.")
    error_count = serializers.IntegerField(help_text="Requests with OTel status Error.")
    error_rate_pct = serializers.FloatField(allow_null=True, help_text="Error share of requests, percent.")
    error_rate_delta_pp = serializers.FloatField(allow_null=True, help_text="Change from the baseline, points.")
    p50_ms = serializers.FloatField(allow_null=True, help_text="Median duration, ms.")
    p95_ms = serializers.FloatField(allow_null=True, help_text="95th percentile duration, ms.")
    p95_change_pct = serializers.FloatField(allow_null=True, help_text="p95 change from the baseline, percent.")
    p99_ms = serializers.FloatField(allow_null=True, help_text="99th percentile duration, ms.")
    baseline_requests = serializers.IntegerField(allow_null=True, help_text="Baseline requests. Null without one.")
    last_seen = serializers.CharField(allow_null=True, help_text="Last span, ISO 8601 UTC.")


@extend_schema_field({"type": "object", "additionalProperties": True})
class _NextQueryField(serializers.JSONField):
    pass


class _ServiceHealthNextCallSerializer(serializers.Serializer):
    tool = serializers.CharField(help_text="The tool to call next.")
    why = serializers.CharField(help_text="What the call answers.")
    query = _NextQueryField(help_text="The prefilled query argument.")


class ServiceHealthResponseSerializer(serializers.Serializer):
    window = _ServiceHealthWindowSerializer(help_text="The absolute UTC windows the server used.")
    summary = _ServiceHealthSummarySerializer(help_text="Counts over all scored services.")
    services = _ServiceHealthRowSerializer(many=True, help_text="One row per service, in orderBy order.")
    next = _ServiceHealthNextCallSerializer(many=True, help_text="Prefilled follow-up calls.")
    truncated = serializers.BooleanField(help_text="True when more services matched than limit.")
    notes = serializers.ListField(child=serializers.CharField(), help_text="Caveats about this result.")
