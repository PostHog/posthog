# ruff: noqa: T201
"""Route the Claude Agent SDK through PostHog's internal Go ai-gateway.

Gated on AI_GATEWAY_URL + AI_GATEWAY_API_KEY; a bad/half-set config falls back to
direct Anthropic instead of failing the review. The gateway is slugless, so the
product rides on a header, not the path.
"""

import json
import os
from urllib.parse import urlparse

# aio_ matches the other cutovers; no $ai_ prefix (gateway strips those).
AI_PRODUCT = "aio_stamphog"


def _misconfig(url: str, api_key: str) -> str | None:
    if not (url and api_key):
        return "AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be set together"
    parsed = urlparse(url)
    # Require an absolute URL: a schemeless value parses all into .path and would
    # pass the /v1 check, arming a broken base instead of falling back.
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "AI_GATEWAY_URL must be an absolute http(s) URL, e.g. https://<host>/v1"
    # A query/fragment survives /v1 stripping and would corrupt the base URL.
    if parsed.query or parsed.fragment:
        return "AI_GATEWAY_URL must not contain a query string or fragment"
    if not parsed.path.rstrip("/").endswith("/v1"):
        return "AI_GATEWAY_URL must include the OpenAI base path, e.g. https://<host>/v1"
    return None


def resolve_gateway_config() -> tuple[str, str] | None:
    """Validated (anthropic_base_url, phs_api_key), or None to use direct Anthropic.

    Trailing /v1 is stripped; the Agent SDK re-appends /v1/messages.
    """
    url = os.environ.get("AI_GATEWAY_URL", "").strip()
    api_key = os.environ.get("AI_GATEWAY_API_KEY", "").strip()
    if not (url or api_key):
        return None
    reason = _misconfig(url, api_key)
    if reason:
        print(f"⚠️  ai-gateway misconfigured, falling back to direct Anthropic: {reason}")
        return None
    # Rebuild from parsed components (not raw-string slicing) so nothing past the
    # path can leak into the base; _misconfig already rejected query/fragment.
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    return f"{parsed.scheme}://{parsed.netloc}{path}", api_key


def _properties_header(properties: dict[str, object]) -> str:
    # Single X-PostHog-Properties JSON blob: the slugless Go gateway merges it onto
    # $ai_generation and ignores per-property x-posthog-property-* headers. None
    # dropped; newlines collapsed so a value can't break the header block.
    clean: dict[str, object] = {}
    for key, value in properties.items():
        if value is None:
            continue
        clean[key] = value.replace("\r", " ").replace("\n", " ") if isinstance(value, str) else value
    if not clean:
        return ""
    return f"X-PostHog-Properties: {json.dumps(clean, separators=(',', ':'))}"


def gateway_env(base_url: str, api_key: str, properties: dict[str, object]) -> dict[str, str]:
    # phs_ secret on both auth vars (SDK sends it as Bearer or x-api-key).
    return {
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_AUTH_TOKEN": api_key,
        "ANTHROPIC_API_KEY": api_key,
        "ANTHROPIC_CUSTOM_HEADERS": _properties_header({"ai_product": AI_PRODUCT, **properties}),
    }
