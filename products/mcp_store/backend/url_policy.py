"""Narrow operator-controlled URL policy for internal MCP dogfooding.

Normal MCP Store URLs must pass PostHog's shared SSRF validation. Cloud operators
may additionally configure complete internal endpoint URLs per team through
``MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM``. Matching is deliberately exact:
this is not a domain, suffix, origin, or CIDR allowlist and cannot authorize
sibling paths or grant another team access.
"""

from django.conf import settings

from posthog.security.url_validation import PinnedUrlVerdict, validate_url_and_pin_ips


def is_internal_mcp_url(url: str, team_id: int | None) -> bool:
    if team_id is None:
        return False
    urls = settings.MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM.get(str(team_id), [])
    return isinstance(urls, list) and url in urls


def resolve_mcp_url_policy(url: str, team_id: int | None) -> PinnedUrlVerdict:
    """The single entry point for MCP URL policy: shared SSRF validation,
    overridden only by an exact team-scoped internal-allowlist match.

    Call sites must use this rather than composing the SSRF validator with
    ``is_internal_mcp_url`` themselves, because a caller that forgets one half
    silently drops the policy.

    A caller that opens a connection to the URL must connect to ``pinned_ips``
    (see ``posthog.security.pinned_httpx``), or use an explicitly trusted proxy
    that validates the address it connects to. Other proxies must fail closed.
    An internal endpoint is reached by name inside the cluster, so its verdict
    pins nothing.
    """
    verdict = validate_url_and_pin_ips(url)
    if verdict.allowed or not is_internal_mcp_url(url, team_id):
        return verdict
    return PinnedUrlVerdict(allowed=True, reason=None, pinned_ips=set())


def check_mcp_url_policy(url: str, team_id: int | None) -> tuple[bool, str | None]:
    """``resolve_mcp_url_policy`` for callers that only need the decision."""
    verdict = resolve_mcp_url_policy(url, team_id)
    return verdict.allowed, verdict.reason


def trust_environment_proxy(url: str, team_id: int | None) -> bool:
    """Allow proxy routing for public URLs, not proxy trust.

    The pinned client separately enforces ``SSRF_TRUSTED_PROXY_URLS``.
    Internal services must be reached directly instead of via HTTP_PROXY.
    """

    return not is_internal_mcp_url(url, team_id)
