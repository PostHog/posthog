import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.proxy_errors import (
    is_transient_proxy_gateway_error,
)


@pytest.mark.parametrize(
    "message",
    [
        # CONNECT-tunnel gateway failures, any 5xx code/reason.
        "Tunnel connection failed: 502 Bad gateway",
        "Tunnel connection failed: 504 Gateway Time-out",
        # Reason phrase capitalisation varies across proxies / urllib3 wordings.
        "OSError('Tunnel connection failed: 502 Bad Gateway')",
        "ProxyError('Cannot connect to proxy.', OSError('Tunnel connection failed: 502 Bad gateway'))",
        "HTTPDriver for https://host:8443 received response code 503 Service Unavailable",
    ],
)
def test_matches_proxy_gateway_blips(message):
    assert is_transient_proxy_gateway_error(message)


@pytest.mark.parametrize(
    "message",
    [
        "certificate verify failed",
        "Code: 516. DB::Exception: Authentication failed",
        "HTTPDriver for https://host:8443 returned response code 404",
        "Connection refused",
    ],
)
def test_ignores_deterministic_and_unrelated_errors(message):
    assert not is_transient_proxy_gateway_error(message)
