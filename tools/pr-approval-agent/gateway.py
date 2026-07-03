# ruff: noqa: T201
"""Route the Claude Agent SDK through PostHog's internal Go ai-gateway.

Gated on AI_GATEWAY_URL + AI_GATEWAY_API_KEY; a bad/half-set config falls back to
direct Anthropic instead of failing the review. The gateway is slugless, so the
product rides on a header, not the path.
"""

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
    anthropic_base = url.rstrip("/")
    anthropic_base = anthropic_base[: -len("/v1")] if anthropic_base.endswith("/v1") else anthropic_base
    return anthropic_base, api_key


def _property_headers(properties: dict[str, object]) -> str:
    # Newlines collapsed so a value can't break the header block; None dropped.
    lines = []
    for key, value in properties.items():
        if value is None:
            continue
        safe = str(value).replace("\r", " ").replace("\n", " ")
        lines.append(f"x-posthog-property-{key}: {safe}")
    return "\n".join(lines)


def gateway_env(base_url: str, api_key: str, properties: dict[str, object]) -> dict[str, str]:
    # phs_ secret on both auth vars (SDK sends it as Bearer or x-api-key).
    return {
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_AUTH_TOKEN": api_key,
        "ANTHROPIC_API_KEY": api_key,
        "ANTHROPIC_CUSTOM_HEADERS": _property_headers({"ai_product": AI_PRODUCT, **properties}),
    }
