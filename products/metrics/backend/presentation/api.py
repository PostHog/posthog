"""DRF views for the alpha metrics product.

Mirrors the shape of `products/logs/backend/api.py` so the two surfaces stay
recognizable.
"""

import datetime as dt
from dataclasses import asdict

from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.event_usage import report_user_action
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle

from products.metrics.backend.facade.api import (
    characterize_metric_anomaly,
    list_metric_event_samples,
    list_metric_names,
    run_metric_query,
    team_has_metrics,
)
from products.metrics.backend.facade.contracts import (
    MAX_CLAUSES_PER_QUERY,
    MetricFilter,
    MetricGroupBy,
    MetricQueryClause,
    MetricQueryRequest,
)
from products.metrics.backend.facade.enums import AttributeScope, FilterOp, MetricAggregation

__all__ = ["MetricsViewSet"]


class _MetricFilterSerializer(serializers.Serializer):
    key = serializers.CharField(
        max_length=255,
        help_text="Attribute name to filter on, without any type-tag suffix (e.g. 'k8s.pod.name', 'env').",
    )
    op = serializers.ChoiceField(
        choices=["eq", "neq", "regex", "not_regex"],
        default="eq",
        help_text="Comparison operator. 'regex'/'not_regex' use RE2 syntax. Negative operators also match rows that lack the key entirely, mirroring Prometheus negative matchers.",
    )
    value = serializers.CharField(
        allow_blank=True,
        max_length=1024,
        help_text="Value to compare against. For regex operators this is the pattern.",
    )
    scope = serializers.ChoiceField(
        choices=["resource", "attribute", "auto"],
        default="auto",
        help_text="Where the attribute lives: 'resource' = per-target resource attributes (k8s.pod.name, service.version), 'attribute' = per-datapoint attributes (http.method, path), 'auto' = resource first with per-datapoint fallback. Use 'auto' unless you know the exact scope.",
    )


class _MetricGroupBySerializer(serializers.Serializer):
    key = serializers.CharField(
        max_length=255,
        help_text="Attribute name to split series by (e.g. 'k8s.pod.name', 'env').",
    )
    scope = serializers.ChoiceField(
        choices=["resource", "attribute", "auto"],
        default="auto",
        help_text="Where the attribute lives; same semantics as filter scope. Use 'auto' unless you know the exact scope.",
    )


class _MetricClauseSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=64,
        help_text="Clause name a formula refers to (e.g. 'a').",
    )
    metricName = serializers.CharField(
        max_length=255,
        help_text="Exact metric name this clause queries.",
    )
    aggregation = serializers.ChoiceField(
        choices=["sum", "avg", "count", "p95", "rate", "increase", "histogram_quantile"],
        default="sum",
        help_text="Aggregation applied per time bucket; same semantics as the top-level aggregation.",
    )
    quantile = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0.0,
        max_value=1.0,
        help_text="Quantile in (0, 1) for 'histogram_quantile'.",
    )
    filters = _MetricFilterSerializer(
        many=True,
        required=False,
        default=list,
        help_text="Label predicates ANDed together for this clause.",
    )
    groupBy = _MetricGroupBySerializer(
        many=True,
        required=False,
        default=list,
        help_text="Labels to split this clause into separate series by.",
    )


class _MetricQueryBodySerializer(serializers.Serializer):
    metricName = serializers.CharField(
        max_length=255,
        required=False,
        help_text="Exact metric name to query (e.g. 'http.server.duration'). Single-clause shorthand — mutually exclusive with 'clauses'.",
    )
    aggregation = serializers.ChoiceField(
        choices=["sum", "avg", "count", "p95", "rate", "increase", "histogram_quantile"],
        default="sum",
        help_text="Aggregation applied per time bucket. 'rate' (per-second) and 'increase' are counter-aware: per-series deltas with Prometheus counter-reset handling, temporality-aware (delta-temporality samples count as-is). 'histogram_quantile' interpolates from OTel histogram buckets and requires 'quantile'.",
    )
    quantile = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0.0,
        max_value=1.0,
        help_text="Quantile in (0, 1) for 'histogram_quantile' (e.g. 0.95). Ignored for other aggregations.",
    )
    filters = _MetricFilterSerializer(
        many=True,
        required=False,
        default=list,
        help_text="Label predicates ANDed together. Rows must satisfy every filter.",
    )
    groupBy = _MetricGroupBySerializer(
        many=True,
        required=False,
        default=list,
        help_text="Labels to split the result into separate series by. Series share one time grid and are capped at the 100 largest.",
    )
    interval = serializers.ChoiceField(
        choices=["second", "minute", "minute_5", "minute_15", "hour", "hour_6", "day", "week"],
        required=False,
        allow_null=True,
        help_text="Bucket size for the shared time grid. Omit to auto-pick (~60 buckets across the range).",
    )
    # mypy can't see DRF's many_init routing max_length to the ListSerializer
    clauses = _MetricClauseSerializer(  # type: ignore[call-arg]
        many=True,
        required=False,
        max_length=MAX_CLAUSES_PER_QUERY,
        help_text=f"Full multi-clause form: each clause is an independent metric selection sharing the request's time grid (maximum {MAX_CLAUSES_PER_QUERY}). Mutually exclusive with 'metricName'.",
    )
    formula = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=512,
        help_text="Arithmetic over clause names evaluated server-side per grid point, e.g. '(a - b) / a'. Supports + - * / and parentheses; division by zero yields 0. When set, only the formula result series are returned.",
    )
    dateFrom = serializers.DateTimeField(
        help_text="Lower bound (inclusive) for the query range. ISO 8601.",
    )
    dateTo = serializers.DateTimeField(
        required=False,
        help_text="Upper bound (exclusive) for the query range. Defaults to now if omitted.",
    )

    def validate(self, attrs: dict) -> dict:
        has_single = bool(attrs.get("metricName"))
        has_clauses = bool(attrs.get("clauses"))
        if has_single == has_clauses:
            raise serializers.ValidationError("Provide exactly one of 'metricName' or 'clauses'.")
        if attrs.get("formula") and not has_clauses:
            raise serializers.ValidationError("'formula' requires 'clauses'.")
        return attrs


class _MetricQueryRequestSerializer(serializers.Serializer):
    query = _MetricQueryBodySerializer(help_text="The metric query to execute.")


def _build_clause(data: dict, *, name: str) -> MetricQueryClause:
    """Validated wire clause (or single-clause shorthand body) → contract.

    The wire aggregation "p95" is contract QUANTILE(0.95)."""
    aggregation_raw: str = data["aggregation"]
    quantile: float | None = None
    if aggregation_raw == "p95":
        aggregation, quantile = MetricAggregation.QUANTILE, 0.95
    elif aggregation_raw == "histogram_quantile":
        aggregation, quantile = MetricAggregation.HISTOGRAM_QUANTILE, data.get("quantile")
    else:
        aggregation = MetricAggregation(aggregation_raw)

    return MetricQueryClause(
        name=name,
        metric_name=data["metricName"],
        aggregation=aggregation,
        quantile=quantile,
        filters=tuple(
            MetricFilter(key=f["key"], op=FilterOp(f["op"]), value=f["value"], scope=AttributeScope(f["scope"]))
            for f in data.get("filters") or []
        ),
        group_by=tuple(
            MetricGroupBy(key=g["key"], scope=AttributeScope(g["scope"])) for g in data.get("groupBy") or []
        ),
    )


class _MetricQueryPointSerializer(serializers.Serializer):
    time = serializers.CharField(help_text="Bucket start as ISO 8601 timestamp.")
    value = serializers.FloatField(
        allow_null=True,
        help_text="Aggregated value for the bucket. Null when the aggregate isn't representable (e.g. float overflow) — render as a gap.",
    )


class _MetricSeriesSerializer(serializers.Serializer):
    labels = serializers.DictField(
        child=serializers.CharField(),
        help_text="Label values identifying this series. Empty for an ungrouped query.",
    )
    points = _MetricQueryPointSerializer(many=True, help_text="Time-bucketed points, ordered by time ascending.")
    metric_name = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Metric the series was computed from. Null for formula results.",
    )
    clause = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Name of the query clause that produced this series.",
    )


class _MetricQueryResponseSerializer(serializers.Serializer):
    results = _MetricSeriesSerializer(
        many=True,
        help_text="One series per (clause, label-set). A single ungrouped query returns exactly one series with empty labels.",
    )


class _MetricAnomalyBodySerializer(serializers.Serializer):
    metricName = serializers.CharField(
        max_length=255,
        help_text="Exact metric name to characterize (e.g. 'metrics_rate_limiter_message_lag_seconds').",
    )
    anomalyFrom = serializers.DateTimeField(
        help_text="Start of the suspicious window (inclusive). ISO 8601 — e.g. when the alert fired or the graph started looking wrong.",
    )
    anomalyTo = serializers.DateTimeField(
        required=False,
        help_text="End of the suspicious window (exclusive). Defaults to now.",
    )
    baselineFrom = serializers.DateTimeField(
        required=False,
        help_text="Start of the healthy comparison window. Defaults to one anomaly-window-length before baselineTo.",
    )
    baselineTo = serializers.DateTimeField(
        required=False,
        help_text="End of the healthy comparison window. Defaults to anomalyFrom. Must not extend past anomalyFrom.",
    )
    aggregation = serializers.ChoiceField(
        choices=["sum", "avg", "count", "p95", "rate", "increase", "histogram_quantile"],
        required=False,
        allow_null=True,
        help_text="Aggregation to characterize. Omit to auto-pick from the metric's OTel type (counter -> rate, gauge -> avg, histogram -> histogram_quantile 0.95).",
    )
    quantile = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0.0,
        max_value=1.0,
        help_text="Quantile for histogram_quantile. Defaults to 0.95.",
    )
    filters = _MetricFilterSerializer(
        many=True,
        required=False,
        default=list,
        help_text="Label predicates narrowing which series are characterized.",
    )
    candidateKeys = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        help_text="Label keys to drill into when finding which label values moved. Omit to auto-discover the most common keys on this metric (plus service_name). Max 4 are used.",
    )


class _MetricAnomalyRequestSerializer(serializers.Serializer):
    query = _MetricAnomalyBodySerializer(help_text="The anomaly characterization to run.")


class _MetricAnomalyDimensionSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Label key that was drilled into.")
    # the name shadows rest_framework Field.label as far as mypy can tell;
    # DRF itself handles declared fields named `label` fine
    label = serializers.CharField(help_text="Label value this row describes.")  # type: ignore[assignment]
    baseline_value = serializers.FloatField(help_text="Mean value over the baseline window for this label value.")
    anomaly_value = serializers.FloatField(help_text="Mean value over the anomaly window for this label value.")
    change_ratio = serializers.FloatField(
        help_text="anomaly_value / baseline_value. A zero baseline yields the anomaly value itself (new traffic)."
    )


class _MetricAnomalyReportSerializer(serializers.Serializer):
    metric_name = serializers.CharField(help_text="Metric that was characterized.")
    aggregation = serializers.CharField(help_text="Aggregation used (auto-picked when not specified).")
    interval = serializers.CharField(help_text="Bucket size of the analysis grid.")
    baseline_from = serializers.CharField(help_text="Baseline window start, ISO 8601.")
    baseline_to = serializers.CharField(help_text="Baseline window end, ISO 8601.")
    anomaly_from = serializers.CharField(help_text="Anomaly window start, ISO 8601.")
    anomaly_to = serializers.CharField(help_text="Anomaly window end, ISO 8601.")
    baseline_mean = serializers.FloatField(help_text="Mean over the baseline window.")
    baseline_stddev = serializers.FloatField(help_text="Population stddev over the baseline window.")
    anomaly_mean = serializers.FloatField(help_text="Mean over the anomaly window.")
    anomaly_peak = serializers.FloatField(help_text="Maximum bucket value in the anomaly window.")
    change_ratio = serializers.FloatField(
        help_text="anomaly_mean / baseline_mean. A zero baseline yields anomaly_mean itself."
    )
    direction = serializers.ChoiceField(
        choices=["up", "down", "flat"], help_text="Which way the metric moved versus the baseline."
    )
    onset_time = serializers.CharField(
        allow_null=True,
        help_text="First bucket clearly outside the baseline range (3 stddevs or 50% relative change), or null if no clear onset.",
    )
    top_movers = _MetricAnomalyDimensionSerializer(
        many=True,
        help_text="Label values whose behavior changed the most between windows, largest change first. Empty when nothing moved or the metric has no labels.",
    )
    series = _MetricSeriesSerializer(
        help_text="The metric across baseline + anomaly windows on one grid, for plotting or further inspection."
    )


class _HasMetricsResponseSerializer(serializers.Serializer):
    hasMetrics = serializers.BooleanField(help_text="Whether the team has ingested any metrics.")


class _MetricValuesParamsSerializer(serializers.Serializer):
    value = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=255,
        help_text="Substring filter (case-insensitive) applied to metric names.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=100,
        min_value=1,
        max_value=1000,
        help_text="Max number of names to return. Defaults to 100; maximum 1000.",
    )


class _MetricNameSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Metric name as it appears in the team's data.")
    metric_type = serializers.CharField(
        help_text="OTel metric type (gauge, sum, histogram, summary, exponential_histogram)."
    )


class _MetricNamesResponseSerializer(serializers.Serializer):
    results = _MetricNameSerializer(many=True, help_text="Distinct metric names ordered by recent activity.")


class _MetricSamplesBodySerializer(serializers.Serializer):
    metricName = serializers.CharField(
        max_length=255,
        help_text="Exact metric name to list raw emissions for (e.g. 'http.server.duration').",
    )
    dateFrom = serializers.DateTimeField(
        help_text="Lower bound (inclusive) for the sample window. ISO 8601.",
    )
    dateTo = serializers.DateTimeField(
        required=False,
        help_text="Upper bound (exclusive) for the sample window. Defaults to now if omitted.",
    )
    traceId = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Restrict to emissions on this trace — the reverse metric->trace pivot. Omit for all traces.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=100,
        min_value=1,
        max_value=1000,
        help_text="Max emissions to return, newest first. Defaults to 100, capped at 1000.",
    )


class _MetricSamplesRequestSerializer(serializers.Serializer):
    query = _MetricSamplesBodySerializer(help_text="The raw-emissions query to execute.")


class _MetricEventSampleSerializer(serializers.Serializer):
    timestamp = serializers.CharField(help_text="When the metric was emitted, ISO 8601.")
    metric_name = serializers.CharField(help_text="Metric this emission belongs to.")
    metric_type = serializers.CharField(
        help_text="OTel metric type: gauge, sum, histogram, summary, or exponential_histogram."
    )
    value = serializers.FloatField(
        help_text="The emitted value. For histogram/summary points this is the distribution sum; pair with count."
    )
    count = serializers.IntegerField(
        help_text="Observations behind this point: 1 for gauges/counters, the distribution count for histograms/summaries."
    )
    unit = serializers.CharField(help_text="Unit of the value, if any.")
    aggregation_temporality = serializers.CharField(
        help_text="For counters: 'delta' or 'cumulative' (decides whether rate() must diff). Empty for gauges."
    )
    is_monotonic = serializers.BooleanField(help_text="True for monotonically increasing counters.")
    service_name = serializers.CharField(help_text="Service that emitted the metric.")
    trace_id = serializers.CharField(
        help_text="Trace this emission belongs to; empty if none. Use it to pivot to the trace.",
    )
    span_id = serializers.CharField(help_text="Span this emission belongs to; empty if none.")
    attributes = serializers.DictField(
        child=serializers.CharField(),
        help_text="Per-emission attributes (high-cardinality labels on the data point).",
    )
    resource_attributes = serializers.DictField(
        child=serializers.CharField(),
        help_text="Attributes of the resource (host, pod, service version) that emitted the metric.",
    )


class _MetricSamplesResponseSerializer(serializers.Serializer):
    results = _MetricEventSampleSerializer(
        many=True,
        help_text="Raw emissions ordered by timestamp descending.",
    )


@extend_schema(tags=["metrics"])
class MetricsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "metrics"
    serializer_class = _FallbackSerializer

    @extend_schema(responses={200: _HasMetricsResponseSerializer})
    @action(detail=False, methods=["GET"], required_scopes=["metrics:read"])
    def has_metrics(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)
        has_metrics = team_has_metrics(self.team)

        report_user_action(
            request.user,
            "metrics has_metrics checked",
            {"has_metrics": has_metrics},
            team=self.team,
            request=request,
        )

        return Response({"hasMetrics": has_metrics}, status=status.HTTP_200_OK)

    @extend_schema(
        parameters=[_MetricValuesParamsSerializer],
        responses={200: _MetricNamesResponseSerializer},
    )
    @action(
        detail=False,
        methods=["GET"],
        required_scopes=["metrics:read"],
        throttle_classes=[ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle],
    )
    def values(self, request: Request, *args, **kwargs) -> Response:
        """Distinct metric names for the team. Backs the picker UI."""
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)

        params = _MetricValuesParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        try:
            results = list_metric_names(
                team=self.team, search=params.validated_data["value"], limit=params.validated_data["limit"]
            )
        except ValueError as exc:
            raise ParseError(str(exc))

        return Response({"results": results}, status=status.HTTP_200_OK)

    @extend_schema(request=_MetricQueryRequestSerializer, responses={200: _MetricQueryResponseSerializer})
    @action(
        detail=False,
        methods=["POST"],
        required_scopes=["metrics:read"],
        throttle_classes=[ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle],
    )
    def query(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)

        body = _MetricQueryRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        query_data = body.validated_data["query"]

        date_to: dt.datetime = query_data.get("dateTo") or timezone.now()
        try:
            if query_data.get("clauses"):
                clauses = tuple(_build_clause(c, name=c["name"]) for c in query_data["clauses"])
            else:
                clauses = (_build_clause(query_data, name="a"),)
            metric_request = MetricQueryRequest(
                clauses=clauses,
                date_from=query_data["dateFrom"],
                date_to=date_to,
                interval=query_data.get("interval"),
                formula=query_data.get("formula"),
            )
            series = run_metric_query(team=self.team, request=metric_request)
        except ValueError as exc:
            raise ParseError(str(exc))

        report_user_action(
            request.user,
            "metrics query ran",
            {
                "aggregations": sorted({c.aggregation.value for c in clauses}),
                "clause_count": len(clauses),
                "has_formula": metric_request.formula is not None,
                "series_count": len(series),
                "result_count": sum(len(s.points) for s in series),
            },
            team=self.team,
            request=request,
        )

        return Response({"results": [asdict(s) for s in series]}, status=status.HTTP_200_OK)

    @extend_schema(request=_MetricSamplesRequestSerializer, responses={200: _MetricSamplesResponseSerializer})
    @action(detail=False, methods=["POST"], required_scopes=["metrics:read"])
    def samples(self, request: Request, *args, **kwargs) -> Response:
        """Raw individual emissions for a metric (the events model), newest
        first — backs the Samples view and the metric->trace pivot."""
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)

        body = _MetricSamplesRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        query_data = body.validated_data["query"]

        try:
            samples = list_metric_event_samples(
                team=self.team,
                metric_name=query_data["metricName"],
                date_from=query_data["dateFrom"],
                date_to=query_data.get("dateTo") or timezone.now(),
                trace_id=query_data.get("traceId") or None,
                limit=query_data.get("limit") or 100,
            )
        except ValueError as exc:
            raise ParseError(str(exc))

        report_user_action(
            request.user,
            "metrics samples listed",
            {"sample_count": len(samples), "has_trace_filter": bool(query_data.get("traceId"))},
            team=self.team,
            request=request,
        )

        return Response({"results": [asdict(s) for s in samples]}, status=status.HTTP_200_OK)

    @extend_schema(request=_MetricAnomalyRequestSerializer, responses={200: _MetricAnomalyReportSerializer})
    @action(
        detail=False,
        methods=["POST"],
        required_scopes=["metrics:read"],
        throttle_classes=[ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle],
    )
    def characterize(self, request: Request, *args, **kwargs) -> Response:
        """Characterize a metric anomaly: compare an anomaly window against a
        baseline, find the onset, and rank which label values moved."""
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)

        body = _MetricAnomalyRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        query_data = body.validated_data["query"]

        filters = tuple(
            MetricFilter(key=f["key"], op=FilterOp(f["op"]), value=f["value"], scope=AttributeScope(f["scope"]))
            for f in query_data.get("filters") or []
        )
        try:
            report = characterize_metric_anomaly(
                team=self.team,
                metric_name=query_data["metricName"],
                anomaly_from=query_data["anomalyFrom"],
                anomaly_to=query_data.get("anomalyTo") or timezone.now(),
                baseline_from=query_data.get("baselineFrom"),
                baseline_to=query_data.get("baselineTo"),
                aggregation=query_data.get("aggregation"),
                quantile=query_data.get("quantile"),
                filters=filters,
                candidate_keys=tuple(query_data["candidateKeys"]) if query_data.get("candidateKeys") else None,
            )
        except ValueError as exc:
            raise ParseError(str(exc))

        report_user_action(
            request.user,
            "metrics anomaly characterized",
            {
                "aggregation": report.aggregation,
                "direction": report.direction,
                "mover_count": len(report.top_movers),
            },
            team=self.team,
            request=request,
        )

        return Response(asdict(report), status=status.HTTP_200_OK)
