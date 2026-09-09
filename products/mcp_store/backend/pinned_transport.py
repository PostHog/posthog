"""Connect-time SSRF validation and DNS pinning for MCP store upstream fetches.

This is the httpx counterpart of ``posthog.security.pinned_requests`` (the
requests-based pinning used by Teams webhook delivery, CIMD and
business_knowledge): ``check_mcp_url_policy`` alone leaves a TOCTOU window,
because the hostname is resolved once for validation (dnspython) and again when
``httpx`` opens the connection (getaddrinfo), so a rebinding DNS record passes
validation and still connects internally.

``ValidatingPinnedTransport`` closes that window with a single resolution at
connect time: each outgoing request is resolved, validated, and its URL is
rewritten to the validated IP so httpx never re-resolves via getaddrinfo.
Validation runs per request — the initial request and every same-origin
redirect retry — so a redirect hop cannot cross into unvalidated address space.

Operator-configured internal endpoints (``MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM``)
are exempt: they point at internal services by design, so their addresses are
trusted and the connection resolves normally.
"""

import urllib.parse as urlparse

import httpx

from posthog.security.pinned_requests import SSRFBlockedError, select_pinned_ip
from posthog.security.url_validation import validate_url_and_pin_ips

from .url_policy import is_internal_mcp_url


class ValidatingPinnedTransport(httpx.HTTPTransport):
    """httpx transport that validates every request URL and pins the connection.

    ``handle_request`` runs for every request sent through the client, so each
    hop gets a fresh resolution + validation and the TCP connection goes to the
    exact IP that was validated. Raises ``SSRFBlockedError`` (fail closed) when a
    URL does not pass validation.
    """

    def __init__(self, url: str, team_id: int | None) -> None:
        super().__init__()
        self._allow_internal = is_internal_mcp_url(url, team_id)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self._allow_internal:
            # Operator-configured internal endpoint: trusted by policy, connect
            # directly like the requests-side machinery trusts its allowlists.
            return super().handle_request(request)

        verdict = validate_url_and_pin_ips(str(request.url))
        if not verdict.allowed:
            raise SSRFBlockedError(verdict.reason or "URL blocked by SSRF protection")

        pinned_ip = select_pinned_ip(verdict.pinned_ips)
        if pinned_ip is None:
            # No IPs to pin (e.g. the dev-mode SSRF bypass) — same pass-through
            # posture as PinnedIPAdapter with an empty pin map.
            return super().handle_request(request)

        # Rewrite the URL to the validated IP so httpx connects to it directly
        # (no second getaddrinfo lookup), while the Host header and TLS SNI /
        # certificate verification keep using the original hostname.
        original_netloc = request.url.netloc.decode("ascii")
        original_host = urlparse.urlparse(f"//{original_netloc}").hostname or ""
        request.headers["Host"] = original_netloc
        request.url = request.url.copy_with(host=str(pinned_ip))
        if original_host:
            # httpcore honors this extension for SNI and certificate checks.
            request.extensions["sni_hostname"] = original_host
        return super().handle_request(request)
