import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.errors import (
    is_transient_egress_proxy_error,
)


@pytest.mark.parametrize(
    "message",
    [
        "HTTPSConnectionPool(host='api.example.com', port=443): Max retries exceeded with url: /v1/things "
        "(Caused by ProxyError('Cannot connect to proxy.', OSError('Tunnel connection failed: 429 Too Many Requests')))",
        "ProxyError('Cannot connect to proxy.', OSError('Tunnel connection failed: 502 Bad gateway'))",
        "Tunnel connection failed: 503 Service Unavailable",
        "Tunnel connection failed: 504 Gateway Timeout",
        "Error HTTPSConnectionPool(host='play.clickhouse.com', port=8443): Max retries exceeded with url: /? "
        "(Caused by ProxyError('Cannot connect to proxy.', TimeoutError('timed out')))",
        "HTTPSConnectionPool(host='login.example.com', port=443): Max retries exceeded with url: /oauth2/token "
        "(Caused by ProxyError('Cannot connect to proxy.', NewConnectionError('<urllib3.connection.HTTPSConnection "
        "object at 0x7f>: Failed to establish a new connection: [Errno 111] Connection refused')))",
    ],
    ids=["tunnel_429", "tunnel_502", "tunnel_503", "tunnel_504", "proxy_connect_timeout", "proxy_connect_refused"],
)
def test_matches_transient_egress_proxy_failures(message: str) -> None:
    assert is_transient_egress_proxy_error(message)


@pytest.mark.parametrize(
    "message",
    [
        "ProxyError('Cannot connect to proxy.', OSError('Tunnel connection failed: 407 Proxy Authentication Required'))",
        "Tunnel connection failed: 403 Forbidden",
        "429 Client Error: Too Many Requests for url: https://api.example.com/v1/things",
        "502 Server Error: Bad Gateway for url: https://api.example.com/v1/things",
    ],
    ids=["proxy_auth_required", "tunnel_forbidden", "vendor_429", "vendor_502"],
)
def test_does_not_match_deterministic_or_vendor_failures(message: str) -> None:
    assert not is_transient_egress_proxy_error(message)
