"""Narrow operator-controlled URL policy for internal MCP dogfooding.

Normal MCP Store URLs must pass PostHog's shared SSRF validation. Cloud operators
may additionally configure complete internal endpoint URLs per team through
``MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM``. Matching is deliberately exact:
this is not a domain, suffix, origin, or CIDR allowlist and cannot authorize
sibling paths or grant another team access.
"""

from django.conf import settings


def is_internal_mcp_url(url: str, team_id: int | None) -> bool:
    if team_id is None:
        return False
    urls = settings.MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM.get(str(team_id), [])
    return isinstance(urls, list) and url in urls


def allow_internal_mcp_url(url: str, team_id: int | None, allowed: bool, reason: str | None) -> tuple[bool, str | None]:
    if not allowed and is_internal_mcp_url(url, team_id):
        return True, None
    return allowed, reason


def trust_environment_proxy(url: str, team_id: int | None) -> bool:
    """Internal Services must be reached directly instead of via HTTP_PROXY."""

    return not is_internal_mcp_url(url, team_id)
