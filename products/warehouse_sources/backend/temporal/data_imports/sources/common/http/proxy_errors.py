"""Classification of CONNECT failures against the egress proxy.

Outbound source traffic goes through the Smokescreen egress proxy, which resolves the
destination host for us. When that resolution fails, Smokescreen answers the CONNECT with
``502 Bad gateway``, and the connector sees
``ProxyError('Cannot connect to proxy.', OSError('Tunnel connection failed: 502 Bad gateway'))``.

That text is the same whether the hostname no longer exists or the proxy could not reach a
host that does, so the message cannot separate a permanent failure from a transient one.
Sources that resolve DNS themselves already treat an unresolvable host as non-retryable (the
``Name or service not known`` entries in clickhouse/source.py and databricks/source.py). The
proxy hop hides the resolver error behind a gateway status, and several sources list that
status as retryable, so a deleted source host is retried on every scheduled run instead.
Resolving the host once restores the existing classification for proxied traffic.
"""

from __future__ import annotations

import re
import socket
import asyncio
from urllib.parse import urlparse

# Stable prefix of `UnresolvableSourceHostError`. `Any_Source_Errors` matches it to pick the
# customer-facing message and disable the schema, so the two must stay in step.
UNRESOLVABLE_SOURCE_HOST_ERROR = "The source's hostname does not exist in DNS"

# Recorded on a run that found the hostname missing while the condition is still inside its grace
# window. `_handle_import_error` counts these across runs to decide when the condition has lasted
# long enough to act on. It must not contain `UNRESOLVABLE_SOURCE_HOST_ERROR` or any other
# `Any_Source_Errors` key, because the finalization activity matches that dict against the recorded
# error text and would disable the schema on the first occurrence, which is what the grace prevents.
UNRESOLVABLE_SOURCE_HOST_PENDING = "The source's hostname did not resolve on this run"

_PROXY_CONNECT_FAILURE_MARKERS = ("cannot connect to proxy", "tunnel connection failed")

# urllib3 names the destination in its pool repr, e.g. `HTTPSConnectionPool(host='x.com', port=443)`.
# Used only when the exception carries no request to read the URL from, which is the case for vendor
# SDKs that re-wrap the failure in their own error type. The pool prefix is part of the pattern
# because an error message can also carry a response body, and a bare `host='...'` search would take
# whatever the source echoed back instead of the destination we connected to.
_POOL_HOST = re.compile(r"HTTPS?ConnectionPool\(host='([^']+)'")

# A hostname we are willing to resolve. The candidate comes out of an error message or a URL, so it
# can be arbitrary text; resolving something that is not a hostname would return NXDOMAIN and
# disable a schema whose real host is alive.
_PLAUSIBLE_HOSTNAME = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9_-]{1,63}(\.[A-Za-z0-9_-]{1,63})*\.?$")

# How long to wait for the resolver. `getaddrinfo` has no timeout of its own, so a wedged resolver
# would otherwise hold this failure path until the activity's own start-to-close timeout.
_RESOLVE_TIMEOUT_SECONDS = 5

# Only a definitive "this name does not exist" is permanent. EAI_AGAIN (a temporary resolver
# failure) and every other socket error stay retryable, so a resolver problem on our side cannot
# disable a source whose host is fine. EAI_NODATA is absent on some platforms.
_PERMANENT_DNS_ERRNOS = frozenset(
    code for code in (getattr(socket, name, None) for name in ("EAI_NONAME", "EAI_NODATA")) if code is not None
)


class UnresolvableSourceHostError(Exception):
    """A source's hostname returned NXDOMAIN, so no retry can reach it."""

    def __init__(self, host: str) -> None:
        super().__init__(f"{UNRESOLVABLE_SOURCE_HOST_ERROR}: {host}")
        self.host = host


def _is_proxy_connect_failure(error: BaseException) -> bool:
    error_msg = str(error).lower()
    return any(marker in error_msg for marker in _PROXY_CONNECT_FAILURE_MARKERS)


def _destination_host(error: BaseException) -> str | None:
    request = getattr(error, "request", None)
    url = getattr(request, "url", None)
    if url:
        try:
            host = urlparse(url).hostname
        except ValueError:
            host = None
        if host and _PLAUSIBLE_HOSTNAME.match(host):
            return host

    match = _POOL_HOST.search(str(error))
    if match and _PLAUSIBLE_HOSTNAME.match(match.group(1)):
        return match.group(1)
    return None


def _resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        return e.errno not in _PERMANENT_DNS_ERRNOS
    except Exception:
        # Anything the resolver raises that is not a name-resolution verdict leaves the question
        # unanswered, so the sync stays retryable. `getaddrinfo` raises `UnicodeError` (not an
        # `OSError`) for a label over 63 characters, and letting that escape would replace the
        # source's real error with a spurious one and lose the actual cause.
        return True
    return True


async def unresolvable_host_behind_proxy(error: BaseException) -> str | None:
    """Return the destination host when ``error`` is a proxy CONNECT failure for a dead hostname.

    Returns ``None`` for any other error, and for a CONNECT failure whose host still resolves,
    because the proxy or the destination can still recover. ``getaddrinfo`` blocks for as long as
    the resolver takes, so it runs off the event loop to keep activity heartbeats on time.

    Every uncertain outcome returns ``None``: an unreadable host, a resolver that does not answer
    in time, and any resolver error short of "this name does not exist". The caller disables the
    customer's schema on a hit, so the cost of a wrong "dead" is much higher than another retry.
    """
    if not _is_proxy_connect_failure(error):
        return None

    host = _destination_host(error)
    if host is None:
        return None

    try:
        resolves = await asyncio.wait_for(asyncio.to_thread(_resolves, host), _RESOLVE_TIMEOUT_SECONDS)
    except TimeoutError:
        return None

    return None if resolves else host
