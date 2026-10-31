import re
from typing import Any

from django.http import HttpResponseBase

from rest_framework.request import Request

from posthog.api.snuffle_proxy import SnuffleProxyViewSet

from products.metrics.backend.prometheus_usage import report_prometheus_api_usage

_LABEL_NAME = r"[A-Za-z_][A-Za-z0-9_]*"


class PrometheusQueryViewSet(SnuffleProxyViewSet):
    """Prometheus-compatible PromQL query API over the team's metrics.

    Mounted at ``/api/projects/:id/metrics/prometheus/api/v1/...`` so a Prometheus client
    pointed at ``/api/projects/:id/metrics/prometheus`` works unchanged. Read-only: remote
    write and remote read are not exposed.
    """

    scope_object = "metrics"
    upstream_prefix = "/api/v1"
    allowed_paths = (
        re.compile(r"query"),
        re.compile(r"query_range"),
        re.compile(r"labels"),
        re.compile(rf"label/{_LABEL_NAME}/values"),
        re.compile(r"series"),
        re.compile(r"metadata"),
        re.compile(r"query_exemplars"),
        re.compile(r"rules"),
        re.compile(r"alerts"),
        re.compile(r"status/buildinfo"),
    )

    def finalize_response(self, request: Request, response: HttpResponseBase, *args: Any, **kwargs: Any) -> Any:
        if self.action == "proxy" and response.status_code < 400:
            report_prometheus_api_usage(request, self.team)
        return super().finalize_response(request, response, *args, **kwargs)
