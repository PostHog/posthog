"""Narrow operator-controlled URL policy for internal MCP dogfooding.

Normal MCP Store URLs must pass PostHog's shared SSRF validation. Cloud operators
may additionally configure complete internal endpoint URLs through
``MCP_STORE_INTERNAL_ALLOWED_URLS``. Matching is deliberately exact: this is not
a domain, suffix, origin, or CIDR allowlist and cannot authorize sibling paths.
"""

from django.conf import settings


def is_internal_mcp_url(url: str) -> bool:
    return url in settings.MCP_STORE_INTERNAL_ALLOWED_URLS


def allow_internal_mcp_url(url: str, allowed: bool, reason: str | None) -> tuple[bool, str | None]:
    if not allowed and is_internal_mcp_url(url):
        return True, None
    return allowed, reason


def trust_environment_proxy(url: str) -> bool:
    """Internal Services must be reached directly instead of via HTTP_PROXY."""

    return not is_internal_mcp_url(url)
