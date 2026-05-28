"""DRF views for the alpha metrics product.

Mirrors the shape of `products/logs/backend/api.py` so the two surfaces stay
recognisable.
"""

import datetime as dt

from django.utils import timezone

from drf_spectacular.types import OpenApiTypes
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

from products.metrics.backend.facade.api import query_metric, team_has_metrics

__all__ = ["MetricsViewSet"]


class _MetricQueryBodySerializer(serializers.Serializer):
    metricName = serializers.CharField(
        max_length=255,
        help_text="Exact metric name to query (e.g. 'http.server.duration').",
    )
    aggregation = serializers.ChoiceField(
        choices=["sum", "avg", "count", "p95"],
        default="sum",
        help_text="Aggregation applied per time bucket.",
    )
    dateFrom = serializers.DateTimeField(
        help_text="Lower bound (inclusive) for the query range. ISO 8601.",
    )
    dateTo = serializers.DateTimeField(
        required=False,
        help_text="Upper bound (exclusive) for the query range. Defaults to now if omitted.",
    )


class _MetricQueryRequestSerializer(serializers.Serializer):
    query = _MetricQueryBodySerializer(help_text="The metric query to execute.")


class _MetricQueryPointSerializer(serializers.Serializer):
    time = serializers.CharField(help_text="Bucket start as ISO 8601 timestamp.")
    value = serializers.FloatField(help_text="Aggregated value for the bucket.")


class _MetricQueryResponseSerializer(serializers.Serializer):
    results = _MetricQueryPointSerializer(many=True, help_text="Time-bucketed points, ordered by time ascending.")


@extend_schema(tags=["metrics"])
class MetricsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "metrics"
    serializer_class = _FallbackSerializer

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
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

    @extend_schema(request=_MetricQueryRequestSerializer, responses={200: _MetricQueryResponseSerializer})
    @action(detail=False, methods=["POST"], required_scopes=["metrics:read"])
    def query(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)

        body = _MetricQueryRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        query_data = body.validated_data["query"]

        date_to: dt.datetime = query_data.get("dateTo") or timezone.now()
        try:
            results = query_metric(
                team=self.team,
                metric_name=query_data["metricName"],
                aggregation=query_data["aggregation"],
                date_from=query_data["dateFrom"],
                date_to=date_to,
            )
        except ValueError as exc:
            raise ParseError(str(exc))

        report_user_action(
            request.user,
            "metrics query ran",
            {
                "aggregation": query_data["aggregation"],
                "result_count": len(results),
            },
            team=self.team,
            request=request,
        )

        return Response({"results": results}, status=status.HTTP_200_OK)
