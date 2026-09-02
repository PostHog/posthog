"""Narrow operator-controlled URL policy for internal MCP dogfooding.

Normal MCP Store URLs must pass PostHog's shared SSRF validation. Cloud operators
may additionally configure complete internal endpoint URLs per team through
``MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM``. Matching is deliberately exact:
this is not a domain, suffix, origin, or CIDR allowlist and cannot authorize
sibling paths or grant another team access.
"""

from django.conf import settings

from posthog.security.url_validation import is_url_allowed


def is_internal_mcp_url(url: str, team_id: int | None) -> bool:
    if team_id is None:
        return False
    urls = settings.MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM.get(str(team_id), [])
    return isinstance(urls, list) and url in urls


def check_mcp_url_policy(url: str, team_id: int | None) -> tuple[bool, str | None]:
    """The single entry point for MCP URL policy: shared SSRF validation,
    overridden only by an exact team-scoped internal-allowlist match.

    Call sites must use this rather than composing ``is_url_allowed`` with
    ``allow_internal_mcp_url`` themselves — a caller that forgets one half (or
    reorders the splatted positional results) silently drops the policy.
    """
    return allow_internal_mcp_url(url, team_id, *is_url_allowed(url))


def allow_internal_mcp_url(url: str, team_id: int | None, allowed: bool, reason: str | None) -> tuple[bool, str | None]:
    if not allowed and is_internal_mcp_url(url, team_id):
        return True, None
    return allowed, reason


def trust_environment_proxy(url: str, team_id: int | None) -> bool:
    """Internal Services must be reached directly instead of via HTTP_PROXY."""

    return not is_internal_mcp_url(url, team_id)
