"""Brand icons for Composio-backed servers.

logo.dev resolves a logo from a brand *domain*, which is a lossy key for the long tail: obscure
B2B vendors are often missing, and the whole provider is unavailable when no publishable key is
configured (the default on self-hosted and in dev). Composio publishes one logo per toolkit slug,
so every app we surface through it has an icon by construction.

Bytes are proxied, never stored, matching how logo.dev icons are handled: the license to cache a
third party's brand assets is not ours to assume. Browsers do the deduplication via Cache-Control.
"""

from __future__ import annotations

import re

from django.http import HttpResponse

import requests
import structlog

from posthog.egress.composio.transport import composio_logo_request
from posthog.egress.transport.transport import EgressBudgetExhausted

logger = structlog.get_logger(__name__)

ICON_CACHE_SECONDS = 60 * 60 * 24

# Composio toolkit slugs are lowercase alphanumerics and underscores. The slug reaches an outbound
# URL, so anything else is rejected rather than escaped — this is the only thing standing between a
# caller-supplied string and a path on someone else's host.
_SLUG_RE = re.compile(r"^[a-z0-9_]{1,64}$")

_ALLOWED_CONTENT_TYPES = ("image/svg+xml", "image/png", "image/jpeg", "image/webp")


def is_valid_toolkit_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug))


def composio_logo_http_response(toolkit_slug: str, *, team_id: int) -> HttpResponse:
    """Proxy one toolkit's logo, or 404 so the caller renders its generic glyph."""
    if not is_valid_toolkit_slug(toolkit_slug):
        return HttpResponse(status=404)

    try:
        response = composio_logo_request(toolkit_slug, source="mcp_store_icons", team_id=team_id)
    except EgressBudgetExhausted:
        # Sheddable by design: a 404 renders the generic glyph rather than failing the page.
        return HttpResponse(status=404)
    except requests.RequestException:
        logger.warning("Composio logo fetch failed", toolkit=toolkit_slug)
        return HttpResponse(status=404)

    if response.status_code != 200:
        return HttpResponse(status=404)

    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        logger.warning("Composio logo had an unexpected content type", toolkit=toolkit_slug, content_type=content_type)
        return HttpResponse(status=404)

    http_response = HttpResponse(response.content, content_type=content_type)
    http_response["Cache-Control"] = f"public, max-age={ICON_CACHE_SECONDS}"
    # These are SVGs from a third party. Loaded through <img> a browser already refuses to run
    # script inside them, but the URL is directly navigable, so the sandbox CSP and nosniff close
    # that path too rather than relying on how the asset happens to be embedded.
    http_response["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
    http_response["X-Content-Type-Options"] = "nosniff"
    return http_response
