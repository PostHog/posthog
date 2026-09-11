"""Reverse-proxy forwarding to Snuffle, the PromQL engine over ClickHouse.

Grafana's Prometheus datasource speaks the Prometheus HTTP API. PostHog owns
authentication, scope, feature flags, throttling and team binding; this module
forwards an already-authorized, team-scoped request to Snuffle and returns its
response. Snuffle runs user-agnostic on a private network and is told only the
team_id, via the X-Team-ID header it is configured to trust
(SNUFFLE_TEAM_SOURCE=header).

The Prometheus wire format (status/data/errorType envelope, form-encoded POST
bodies, GET query params) is foreign to PostHog's JSON API, so this forwards
raw bytes and passes the upstream status through verbatim — Grafana renders
`error` from the envelope and keys behavior off 400/422/503.
"""

import re
import base64
from urllib.parse import parse_qsl, urlencode

from django.conf import settings

import httpx

from posthog.security.outbound_proxy import internal_httpx_client

from products.metrics.backend.facade.contracts import PrometheusUpstreamResponse, PrometheusUpstreamUnavailable

# Prometheus read paths Grafana may call. `write` is deliberately absent: it
# would bypass the Kafka ingest and series fingerprinting. `read` (remote
# read) is a bulk-export surface with no cost cap and Grafana does not need it.
_ALLOWED_EXACT = frozenset(
    {
        "query",
        "query_range",
        "series",
        "labels",
        "metadata",
        "status/buildinfo",
        "query_exemplars",
        "rules",
        "alerts",
    }
)
_LABEL_VALUES_RE = re.compile(r"^label/[^/]+/values$")


def is_allowed_prometheus_path(path: str) -> bool:
    """True only for the read-only Prometheus paths Grafana uses."""
    path = path.strip("/")
    if not path or ".." in path:
        return False
    return path in _ALLOWED_EXACT or bool(_LABEL_VALUES_RE.match(path))


def _strip_tenant_params(query_string: str) -> str:
    # The tenant is bound by the proxy from the URL team; a client must not
    # also assert one via query param. Snuffle in header mode ignores these
    # anyway, but they are dropped so a misconfigured Snuffle cannot honor one.
    pairs = [(k, v) for k, v in parse_qsl(query_string, keep_blank_values=True) if k not in ("team_id", "tenant")]
    return urlencode(pairs)


def forward_prometheus_request(
    *,
    team_id: int,
    method: str,
    upstream_path: str,
    query_string: str,
    body: bytes,
    content_type: str,
    accept: str,
    transport: "httpx.BaseTransport | None" = None,
) -> PrometheusUpstreamResponse:
    base_url = settings.METRICS_PROMQL_INTERNAL_URL.rstrip("/")
    if not base_url:
        raise PrometheusUpstreamUnavailable("PromQL backend is not configured")

    url = f"{base_url}/api/v1/{upstream_path.strip('/')}"
    if query_string:
        url = f"{url}?{_strip_tenant_params(query_string)}"

    headers: dict[str, str] = {"X-Team-ID": str(team_id)}
    if content_type:
        headers["Content-Type"] = content_type
    if accept:
        headers["Accept"] = accept
    basic_auth = settings.METRICS_PROMQL_INTERNAL_BASIC_AUTH
    if basic_auth:
        headers["Authorization"] = "Basic " + base64.b64encode(basic_auth.encode()).decode()

    timeout = httpx.Timeout(settings.METRICS_PROMQL_TIMEOUT_SECONDS, connect=2.0)
    client_kwargs: dict = {"timeout": timeout}
    if transport is not None:
        client_kwargs["transport"] = transport

    try:
        with internal_httpx_client(**client_kwargs) as client:
            response = client.request(method, url, content=body if method in ("POST", "PUT", "PATCH") else None, headers=headers)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
        # Do not leak the upstream URL or exception text into the response.
        raise PrometheusUpstreamUnavailable("PromQL backend is unreachable") from exc

    return PrometheusUpstreamResponse(
        status_code=response.status_code,
        content=response.content,
        content_type=response.headers.get("content-type", "application/json"),
    )
