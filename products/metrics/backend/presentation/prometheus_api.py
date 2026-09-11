"""Grafana-facing Prometheus HTTP API: a thin, authorized reverse proxy to Snuffle.

Grafana's Prometheus datasource speaks the Prometheus wire format, which is not
PostHog's JSON API. PostHog owns auth, scope, feature flags, throttling and
team binding here, then forwards the request to Snuffle (the PromQL engine
over ClickHouse) with the team bound from the URL. Snuffle is user-agnostic and
runs on a private network; the only tenant it is told is the one from the URL.

Separate from `presentation/api.py` because the Prometheus surface is a foreign
wire format excluded from OpenAPI/MCP codegen, and `api.py` is already large.
"""

import json
import time
from typing import cast

from django.http import HttpResponse

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import (
    FEATURE_FLAG_REQUIRED_ERROR_CODE,
    PostHogFeatureFlagPermission,
    posthog_feature_flag_enabled,
)
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle

from products.metrics.backend.facade.api import forward_prometheus_request, is_allowed_prometheus_path
from products.metrics.backend.facade.contracts import (
    METRICS_FEATURE_FLAG,
    METRICS_PROMETHEUS_API_FEATURE_FLAG,
    PrometheusUpstreamUnavailable,
)

__all__ = ["PrometheusMetricsViewSet"]


def _envelope(error_type: str, error: str) -> dict:
    return {"status": "error", "errorType": error_type, "error": error}


class _PrometheusApiFeatureFlagPermission(BasePermission):
    """ANDs the prometheus-api flag on top of the metrics alpha flag.

    PostHogFeatureFlagPermission returns on the first enabled flag, so the two
    flags cannot be combined in one dict config; this is the second check.
    """

    code = FEATURE_FLAG_REQUIRED_ERROR_CODE

    def has_permission(self, request: Request, view: APIView) -> bool:
        team = cast(TeamAndOrgViewSetMixin, view).team
        return bool(
            posthog_feature_flag_enabled(
                METRICS_PROMETHEUS_API_FEATURE_FLAG,
                str(cast(User, request.user).distinct_id),
                organization_id=team.organization_id,
                team_id=team.pk,
            )
        )


@extend_schema(exclude=True)
class PrometheusMetricsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "metrics"
    posthog_feature_flag = METRICS_FEATURE_FLAG
    permission_classes = [PostHogFeatureFlagPermission, _PrometheusApiFeatureFlagPermission]

    @action(
        detail=False,
        methods=["GET", "POST"],
        url_path=r"api/v1/(?P<upstream_path>.+)",
        required_scopes=["metrics:read"],
        throttle_classes=[ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle],
    )
    def prometheus(self, request: Request, upstream_path: str, *args, **kwargs) -> HttpResponse:
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)
        # The router's optional trailing slash sits after the greedy capture.
        upstream_path = upstream_path.rstrip("/")

        if not is_allowed_prometheus_path(upstream_path):
            return HttpResponse(
                _json(_envelope("not_found", f"{upstream_path!r} is not served by the PostHog Prometheus API")),
                status=status.HTTP_404_NOT_FOUND,
                content_type="application/json",
            )

        started = time.monotonic()
        try:
            upstream = forward_prometheus_request(
                team_id=self.team.pk,
                method=request.method or "GET",
                upstream_path=upstream_path,
                # Raw query string and body are forwarded; the proxy strips
                # tenant params and never touches request.data, so Grafana's
                # form-encoded POST bodies pass through untouched.
                query_string=request._request.META.get("QUERY_STRING", ""),
                body=request._request.body,
                content_type=request.content_type or "",
                accept=request.headers.get("Accept", ""),
            )
            response = HttpResponse(upstream.content, status=upstream.status_code, content_type=upstream.content_type)
            upstream_status: int | None = upstream.status_code
        except PrometheusUpstreamUnavailable as exc:
            response = HttpResponse(
                _json(_envelope("unavailable", str(exc))),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
                content_type="application/json",
            )
            upstream_status = None

        report_user_action(
            request.user,
            "metrics prometheus api called",
            {
                "endpoint": upstream_path,
                "method": request.method,
                "upstream_status": upstream_status,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "client": "grafana" if request.headers.get("User-Agent", "").startswith("Grafana") else "other",
            },
            team=self.team,
            request=request,
        )
        return response


def _json(payload: dict) -> bytes:
    return json.dumps(payload).encode()
