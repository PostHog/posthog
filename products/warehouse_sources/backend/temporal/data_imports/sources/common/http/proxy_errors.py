"""Classify transient egress-proxy gateway failures.

All data-warehouse outbound traffic flows through the Smokescreen egress proxy.
When the proxy briefly can't reach an upstream host it returns a gateway error
on the HTTPS `CONNECT` tunnel, which surfaces as
`OSError: Tunnel connection failed: 502 Bad gateway` (clickhouse-connect /
urllib3) or `ProxyError: Cannot connect to proxy` (requests). These are
transient blips, not deterministic config errors: a fresh attempt recovers. So
callers should retry them rather than fail on attempt 1 and bury real failures
under error-tracking noise.
"""

from __future__ import annotations

# Matched case-insensitively — proxy reason phrases vary in capitalisation
# ("Bad gateway" vs "Bad Gateway") across proxy and urllib3 wordings. The two
# tunnel/proxy substrings cover every 5xx CONNECT-tunnel failure regardless of
# the specific status code; the numeric entries also catch forward-proxy
# (plain HTTP) responses that surface the code without the tunnel wording.
_TRANSIENT_PROXY_GATEWAY_SUBSTRINGS: tuple[str, ...] = (
    "tunnel connection failed",
    "cannot connect to proxy",
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway time-out",
    "504 gateway timeout",
)


def is_transient_proxy_gateway_error(message: str) -> bool:
    """Whether an error message denotes a transient egress-proxy gateway blip."""
    lowered = message.lower()
    return any(substring in lowered for substring in _TRANSIENT_PROXY_GATEWAY_SUBSTRINGS)
