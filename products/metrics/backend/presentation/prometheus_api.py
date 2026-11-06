import re
from typing import Any, cast

from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.snuffle_proxy import SnuffleProxyViewSet
from posthog.auth import PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.event_usage import get_request_analytics_properties
from posthog.models import User

from products.metrics.backend.facade.api import record_promql_query, report_prometheus_api_usage

_LABEL_NAME = r"[A-Za-z_][A-Za-z0-9_]*"


def _auth_method(request: Request) -> str:
    authenticator = request.successful_authenticator
    if isinstance(authenticator, PersonalAPIKeyAuthentication):
        return "personal_api_key"
    if isinstance(authenticator, SessionAuthentication):
        return "session"
    return "other"


def _client(request: Request) -> str:
    # Grafana sends `Grafana/<version>` as the user agent of data source requests.
    return "grafana" if request.headers.get("User-Agent", "").startswith("Grafana/") else "other"


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

    def finalize_response(self, request: Request, response: Response, *args: Any, **kwargs: Any) -> Any:
        if self.action == "proxy" and response.status_code < 400:
            report_prometheus_api_usage(
                team=self.team,
                user=cast(User, request.user),
                auth_method=_auth_method(request),
                client=_client(request),
                analytics_props=get_request_analytics_properties(request),
            )
        return super().finalize_response(request, response, *args, **kwargs)
