"""How the MCP Store reaches an upstream server it was given the URL of.

A team supplies the URL, so every fetch has to pass the SSRF policy in
``url_policy`` and then reach the address that policy accepted. Validating and
connecting are two steps, and a hostname can resolve differently in each, so the
client pins the connection to the validated address instead of letting ``httpx``
resolve the name a second time.

Call ``validate_upstream_url`` first and hand its verdict to
``upstream_mcp_client``: the client cannot be built without one, so a fetch
cannot skip the policy.
"""

import httpx

from posthog.security.pinned_httpx import pinned_httpx_client
from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import PinnedUrlVerdict, validate_url_and_pin_ips

from .url_policy import allow_internal_mcp_url, trust_environment_proxy


def validate_upstream_url(url: str, team_id: int | None) -> PinnedUrlVerdict:
    """The MCP URL policy, plus the addresses a fetch of that URL must pin to.

    Same policy as ``check_mcp_url_policy``, which stays the entry point for a save
    path that only gates a URL. An operator-allowlisted internal URL carries no
    pinned addresses: it names a service we run, not a name a team controls.
    """
    verdict = validate_url_and_pin_ips(url)
    if verdict.allowed:
        return verdict
    allowed, reason = allow_internal_mcp_url(url, team_id, verdict.allowed, verdict.reason)
    return PinnedUrlVerdict(allowed=allowed, reason=reason, pinned_ips=set())


def upstream_mcp_client(url: str, team_id: int | None, verdict: PinnedUrlVerdict, *, timeout: float) -> httpx.Client:
    """Client pinned to the addresses ``verdict`` validated for ``url``.

    Raises ``SSRFBlockedError`` on a verdict that blocks the URL, so a caller that
    forgets to act on the verdict still cannot reach the host. The caller owns the
    client and must close it.
    """
    if not verdict.allowed:
        raise SSRFBlockedError(verdict.reason or "URL blocked by SSRF protection")
    return pinned_httpx_client(
        url,
        verdict.pinned_ips,
        timeout=timeout,
        trust_env=trust_environment_proxy(url, team_id),
    )
