import re

from rest_framework.request import Request

from posthog.api.snuffle_proxy import SnuffleProxyViewSet

from products.metrics.backend.facade.api import record_promql_query

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

    def before_forward(self, request: Request, path: str) -> None:
        if path not in ("query", "query_range"):
            return
        # The Prometheus API takes the query from the form body of a POST or from the query string.
        expr = request.data.get("query") or request.query_params.get("query")
        if expr:
            record_promql_query(team=self.team, expr=expr)
