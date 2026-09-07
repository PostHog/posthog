import json
import socket
import ipaddress
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from unittest.mock import MagicMock, patch

import httpx

from posthog.security.url_validation import PinnedUrlVerdict

from products.mcp_store.backend import pinned_transport as pt


def _verdict(allowed: bool, reason: str | None = None, ips: set[str] | None = None) -> PinnedUrlVerdict:
    return PinnedUrlVerdict(
        allowed=allowed, reason=reason, pinned_ips={ipaddress.ip_address(ip) for ip in (ips or set())}
    )


class TestValidatingPinnedTransport:
    def test_blocked_url_raises_before_any_connection(self):
        # A URL whose resolution fails SSRF validation must never reach the
        # socket layer — no connection, no credential leaves the process.
        transport = pt.ValidatingPinnedTransport.__new__(pt.ValidatingPinnedTransport)
        transport._allow_internal = False
        request = httpx.Request("POST", "http://rebind.attacker.test/mcp", content=b"{}")

        with (
            patch.object(
                pt, "validate_url_and_pin_ips", return_value=_verdict(False, "Local/Loopback host not allowed")
            ),
            patch.object(httpx.HTTPTransport, "handle_request") as super_handle,
        ):
            with pytest.raises(pt.SSRFBlockedError, match="Loopback"):
                transport.handle_request(request)
        super_handle.assert_not_called()

    @pytest.mark.parametrize(
        "ip,expected_netloc",
        [
            ("93.184.216.34", "93.184.216.34:8443"),
            ("2001:db8::1", "[2001:db8::1]:8443"),
        ],
    )
    def test_rewrites_url_to_pinned_ip_and_preserves_host_header(self, ip, expected_netloc):
        # The connection goes to the validated IP (no second getaddrinfo) while
        # the Host header and TLS SNI keep the original hostname.
        transport = pt.ValidatingPinnedTransport.__new__(pt.ValidatingPinnedTransport)
        transport._allow_internal = False
        request = httpx.Request("POST", "https://mcp.example.org:8443/path?q=1", content=b"{}")

        with (
            patch.object(pt, "validate_url_and_pin_ips", return_value=_verdict(True, ips={ip})),
            patch.object(httpx.HTTPTransport, "handle_request", return_value=MagicMock()),
        ):
            transport.handle_request(request)

        assert str(request.url) == f"https://{expected_netloc}/path?q=1"
        assert request.headers["Host"] == "mcp.example.org:8443"
        assert request.extensions["sni_hostname"] == "mcp.example.org"

    def test_no_pins_passes_through_untouched(self):
        # Empty pin set means pinning was intentionally skipped (dev SSRF
        # bypass); the request must connect normally, not fail closed.
        transport = pt.ValidatingPinnedTransport.__new__(pt.ValidatingPinnedTransport)
        transport._allow_internal = False
        request = httpx.Request("POST", "https://mcp.example.org/mcp", content=b"{}")

        with (
            patch.object(pt, "validate_url_and_pin_ips", return_value=_verdict(True)),
            patch.object(httpx.HTTPTransport, "handle_request", return_value=MagicMock()) as super_handle,
        ):
            transport.handle_request(request)

        super_handle.assert_called_once()
        assert str(request.url) == "https://mcp.example.org/mcp"
        assert "Host" not in request.headers
        assert "sni_hostname" not in request.extensions

    def test_internal_allowlisted_endpoints_skip_validation(self):
        # Operator-configured internal URLs (MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM)
        # are trusted by policy and must keep resolving normally.
        transport = pt.ValidatingPinnedTransport.__new__(pt.ValidatingPinnedTransport)
        transport._allow_internal = True
        request = httpx.Request("POST", "http://internal.service:8000/mcp", content=b"{}")

        with (
            patch.object(pt, "validate_url_and_pin_ips") as validate,
            patch.object(httpx.HTTPTransport, "handle_request", return_value=MagicMock()) as super_handle,
        ):
            transport.handle_request(request)

        validate.assert_not_called()
        super_handle.assert_called_once()
        assert str(request.url) == "http://internal.service:8000/mcp"

    def test_each_request_is_revalidated(self):
        # handle_request runs per hop, so a redirect retry hits validation again
        # with the redirect URL — no cached "already validated" state exists.
        transport = pt.ValidatingPinnedTransport.__new__(pt.ValidatingPinnedTransport)
        transport._allow_internal = False

        with (
            patch.object(
                pt, "validate_url_and_pin_ips", return_value=_verdict(True, ips={"93.184.216.34"})
            ) as validate,
            patch.object(httpx.HTTPTransport, "handle_request", return_value=MagicMock()),
        ):
            transport.handle_request(httpx.Request("POST", "http://rebind.attacker.test/mcp", content=b"{}"))
            transport.handle_request(httpx.Request("POST", "http://rebind.attacker.test/mcp/", content=b"{}"))

        assert validate.call_count == 2


class TestPinnedConnection:
    def test_connection_uses_validated_ip_not_dns(self):
        """End-to-end rebinding check over a real socket.

        Validation resolves the host to the loopback server; DNS (getaddrinfo) is
        poisoned to a dead address. The fetch only succeeds if the connection
        uses the validated IP instead of re-resolving — the DNS-rebinding window
        this transport exists to close.
        """
        received: dict[str, str] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received["host"] = self.headers.get("Host", "")
                received["authorization"] = self.headers.get("Authorization", "")
                body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
                received["body"] = body
                out = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()

        transport = pt.ValidatingPinnedTransport.__new__(pt.ValidatingPinnedTransport)
        transport._allow_internal = False

        original_getaddrinfo = socket.getaddrinfo

        def rebound_getaddrinfo(host, *args, **kwargs):
            if host == "rebind.attacker.test":
                # Where an unpatched httpx stack would connect (the rebind).
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.2", port))]
            return original_getaddrinfo(host, *args, **kwargs)

        try:
            with (
                patch.object(
                    pt,
                    "validate_url_and_pin_ips",
                    return_value=_verdict(True, ips={"127.0.0.1"}),
                ),
                patch("socket.getaddrinfo", side_effect=rebound_getaddrinfo),
            ):
                with httpx.Client(transport=transport, trust_env=False) as client:
                    response = client.post(
                        f"http://rebind.attacker.test:{port}/mcp",
                        content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode(),
                        headers={"Authorization": "Bearer sk-test-upstream"},
                    )
            assert response.status_code == 200
            assert json.loads(response.text)["result"] == {"tools": []}
            assert received["host"] == f"rebind.attacker.test:{port}"
            assert received["authorization"] == "Bearer sk-test-upstream"
        finally:
            server.shutdown()
