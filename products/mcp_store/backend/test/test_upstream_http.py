import ipaddress

import pytest
from unittest.mock import patch

from django.test import override_settings

import httpx

from posthog.security.pinned_httpx import PinnedIPTransport
from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import PinnedUrlVerdict

from products.mcp_store.backend.upstream_http import upstream_mcp_client, validate_upstream_url

PUBLIC_IP = ipaddress.ip_address("93.184.216.34")
INTERNAL_URL = "http://grafana-mcp.monitoring.svc.cluster.local/mcp"


class TestValidateUpstreamUrl:
    @patch("posthog.security.url_validation.resolve_host_ips", return_value={PUBLIC_IP})
    def test_allowed_url_carries_the_addresses_it_was_validated_on(self, _resolve) -> None:
        verdict = validate_upstream_url("https://mcp.example.com/mcp", 42)

        assert verdict.allowed
        assert verdict.pinned_ips == {PUBLIC_IP}

    @patch("posthog.security.url_validation.resolve_host_ips", return_value={ipaddress.ip_address("10.0.0.7")})
    def test_blocked_url_carries_no_addresses(self, _resolve) -> None:
        verdict = validate_upstream_url("https://mcp.example.com/mcp", 42)

        assert not verdict.allowed
        assert verdict.pinned_ips == set()

    @override_settings(MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM={"42": [INTERNAL_URL]})
    def test_operator_allowlisted_url_is_allowed_without_pins(self) -> None:
        verdict = validate_upstream_url(INTERNAL_URL, 42)

        assert verdict.allowed
        assert verdict.pinned_ips == set()


class TestUpstreamMcpClient:
    def test_a_blocked_verdict_refuses_to_build_a_client(self) -> None:
        verdict = PinnedUrlVerdict(allowed=False, reason="Private IP address not allowed", pinned_ips=set())

        with pytest.raises(SSRFBlockedError, match="Private IP"):
            upstream_mcp_client("https://mcp.example.com/mcp", 42, verdict, timeout=10)

    def test_client_connects_to_the_validated_address(self) -> None:
        verdict = PinnedUrlVerdict(allowed=True, reason=None, pinned_ips={PUBLIC_IP})

        with upstream_mcp_client("https://mcp.example.com/mcp", 42, verdict, timeout=10) as client:
            assert isinstance(client._transport, PinnedIPTransport)
            with patch.object(httpx.HTTPTransport, "handle_request", return_value=httpx.Response(200)) as handle:
                client.send(client.build_request("POST", "https://mcp.example.com/mcp"))

        assert str(handle.call_args.args[0].url) == f"https://{PUBLIC_IP}/mcp"
