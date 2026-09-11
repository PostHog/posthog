"""Forwarding-logic tests for the Prometheus reverse proxy.

No Django client and no live Snuffle: the upstream is an httpx.MockTransport
that records the request Snuffle would receive, so these assert exactly what
crosses the wire — the team header, the allowlist, and that client-asserted
tenant/auth headers never reach Snuffle.
"""

import json

import pytest
from unittest.mock import patch

import httpx

from products.metrics.backend.prometheus_proxy import (
    PrometheusUpstreamUnavailable,
    forward_prometheus_request,
    is_allowed_prometheus_path,
)

BASE = "http://snuffle:9091"


@pytest.mark.parametrize(
    "path,expected",
    [
        ("query", True),
        ("query_range", True),
        ("series", True),
        ("labels", True),
        ("label/job/values", True),
        ("label/__name__/values", True),
        ("metadata", True),
        ("status/buildinfo", True),
        ("query_exemplars", True),
        ("rules", True),
        ("alerts", True),
        # write/read must never be proxied: write bypasses the Kafka ingest and
        # series fingerprinting, read is a bulk-export surface with no cost cap.
        ("write", False),
        ("read", False),
        ("admin/tsdb/snapshot", False),
        ("status/config", False),
        ("status/runtimeinfo", False),
        ("format_query", False),
        ("targets", False),
        ("label//values", False),
        ("../query", False),
        ("", False),
        ("query/evil", False),
    ],
)
def test_is_allowed_prometheus_path(path: str, expected: bool) -> None:
    assert is_allowed_prometheus_path(path) is expected


def _forward(captured: dict, **kwargs) -> httpx.Response:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return kwargs.pop("response")

    transport = httpx.MockTransport(handler)
    with patch("products.metrics.backend.prometheus_proxy.settings") as mock_settings:
        mock_settings.METRICS_PROMQL_INTERNAL_URL = BASE
        mock_settings.METRICS_PROMQL_INTERNAL_BASIC_AUTH = ""
        mock_settings.METRICS_PROMQL_TIMEOUT_SECONDS = 60.0
        return forward_prometheus_request(
            team_id=42,
            method=kwargs.get("method", "GET"),
            upstream_path=kwargs.get("upstream_path", "query_range"),
            query_string=kwargs.get("query_string", "query=up&start=1"),
            body=kwargs.get("body", b""),
            content_type=kwargs.get("content_type", ""),
            accept=kwargs.get("accept", ""),
            transport=transport,
        )


def test_forward_sets_team_header_and_strips_client_tenant_and_auth() -> None:
    captured: dict = {}
    _forward(captured, response=httpx.Response(200, json={"status": "success", "data": {}}))
    req = captured["request"]
    assert req.url.path == "/api/v1/query_range"
    assert req.url.query == b"query=up&start=1"
    assert req.headers["X-Team-ID"] == "42"
    # Client-supplied tenant and auth must never reach Snuffle.
    assert "Authorization" not in req.headers or not req.headers["Authorization"].startswith("Bearer")


def test_forward_overrides_client_supplied_team_header() -> None:
    # A Grafana config that happens to send its own X-Team-ID must not pick a tenant.
    captured: dict = {}
    _forward(
        captured,
        response=httpx.Response(200, json={}),
        query_string="query=up&team_id=999",
    )
    req = captured["request"]
    assert req.headers["X-Team-ID"] == "42"
    assert b"team_id" not in req.url.query


def test_forward_post_body_and_content_type() -> None:
    captured: dict = {}
    body = b"query=sum%20by%20(job)(rate(x%5B5m%5D))&start=1&end=2&step=60"
    _forward(
        captured,
        response=httpx.Response(200, json={}),
        method="POST",
        body=body,
        content_type="application/x-www-form-urlencoded",
    )
    req = captured["request"]
    assert req.method == "POST"
    assert req.content == body
    assert req.headers["Content-Type"] == "application/x-www-form-urlencoded"


def test_forward_sends_service_basic_auth_when_configured() -> None:
    captured: dict = {}
    with patch("products.metrics.backend.prometheus_proxy.settings") as mock_settings:
        mock_settings.METRICS_PROMQL_INTERNAL_URL = BASE
        mock_settings.METRICS_PROMQL_INTERNAL_BASIC_AUTH = "snuffle_ro:secret"
        mock_settings.METRICS_PROMQL_TIMEOUT_SECONDS = 60.0
        forward_prometheus_request(
            team_id=42,
            method="GET",
            upstream_path="query",
            query_string="query=1",
            body=b"",
            content_type="",
            accept="",
            transport=httpx.MockTransport(lambda r: (captured.update(request=r), httpx.Response(200, json={}))[1]),
        )
    assert captured["request"].headers["Authorization"] == "Basic c251ZmZsZV9ybzpzZWNyZXQ="


def test_forward_passes_through_upstream_status_and_body() -> None:
    body = {"status": "error", "errorType": "bad_data", "error": "parse error"}
    result = _forward({}, response=httpx.Response(422, json=body))
    assert result.status_code == 422
    assert json.loads(result.content) == body
    assert result.content_type.startswith("application/json")


def test_upstream_unavailable_maps_to_503() -> None:
    with patch("products.metrics.backend.prometheus_proxy.settings") as mock_settings:
        mock_settings.METRICS_PROMQL_INTERNAL_URL = BASE
        mock_settings.METRICS_PROMQL_INTERNAL_BASIC_AUTH = ""
        mock_settings.METRICS_PROMQL_TIMEOUT_SECONDS = 60.0
        with pytest.raises(PrometheusUpstreamUnavailable):
            forward_prometheus_request(
                team_id=42,
                method="GET",
                upstream_path="query",
                query_string="query=1",
                body=b"",
                content_type="",
                accept="",
                transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused"))),
            )


def test_unconfigured_url_raises_unavailable() -> None:
    with patch("products.metrics.backend.prometheus_proxy.settings") as mock_settings:
        mock_settings.METRICS_PROMQL_INTERNAL_URL = ""
        mock_settings.METRICS_PROMQL_INTERNAL_BASIC_AUTH = ""
        mock_settings.METRICS_PROMQL_TIMEOUT_SECONDS = 60.0
        with pytest.raises(PrometheusUpstreamUnavailable):
            forward_prometheus_request(
                team_id=42,
                method="GET",
                upstream_path="query",
                query_string="query=1",
                body=b"",
                content_type="",
                accept="",
            )
