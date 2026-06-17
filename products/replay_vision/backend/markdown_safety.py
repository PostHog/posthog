"""Neutralize externally-hosted URLs in LLM-generated report content.

Ported from `products/exports/backend/temporal/subscriptions/ai_subscription/delivery.py`
rather than imported — that lives in a private (underscore) function and pulling it across
the product boundary for one helper isn't worth the coupling. Synthesized group summary content is
delivered to Slack (which auto-unfurls links), so injected/hallucinated URLs must be defanged
to inert code spans before delivery; only PostHog hosts survive.
"""

import re
from urllib.parse import urlparse

from posthog.api.utils import hostname_in_allowed_url_list

_ALLOWED_LINK_URLS = ["https://posthog.com", "https://*.posthog.com"]
# Title may be double-quoted, single-quoted, or parenthesized (all CommonMark forms) — match all
# three so a crafted title doesn't leave the URL un-defanged.
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(((?:[^()\s]+|\([^)]*\))+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\)")
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_AUTOLINK_RE = re.compile(r"<(https?://[^\s>]+)>", re.IGNORECASE)
_BARE_URL_RE = re.compile(r"(?<!\]\()(?<![<`@])((?:https?://|www\.)[^\s<>)\]`]+)", re.IGNORECASE)


def _is_allowed_link_url(url: str) -> bool:
    if "\\" in url or any(c.isspace() or ord(c) < 0x20 for c in url):
        return False
    try:
        parsed = urlparse(url)
        if parsed.username is not None or parsed.password is not None:
            return False
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    return hostname_in_allowed_url_list(_ALLOWED_LINK_URLS, host)


def _neutralize_url(url: str, keep_as: str | None = None) -> str:
    check_url = url if url.lower().startswith(("http://", "https://")) else f"https://{url}"
    if _is_allowed_link_url(check_url):
        return keep_as if keep_as is not None else url
    return f"`{url}`"


def strip_external_links_markdown(markdown: str) -> str:
    """Drop images, keep only PostHog links, and defang every other URL to a code span."""
    md = _MARKDOWN_IMAGE_RE.sub(lambda m: m.group(1) or "", markdown)
    md = _MARKDOWN_LINK_RE.sub(
        lambda m: m.group(0) if _is_allowed_link_url(m.group(2)) else m.group(1),
        md,
    )
    md = _AUTOLINK_RE.sub(lambda m: _neutralize_url(m.group(1), keep_as=m.group(0)), md)
    md = _BARE_URL_RE.sub(lambda m: _neutralize_url(m.group(1)), md)
    return md
