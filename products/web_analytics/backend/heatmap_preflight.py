import re
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache

import requests
import structlog

from posthog.security.pinned_requests import SSRFBlockedError, pinned_session
from posthog.security.url_validation import strip_userinfo

logger = structlog.get_logger(__name__)

Framing = Literal["allowed", "blocked", "unknown"]
BlockedBy = Literal["x_frame_options", "frame_ancestors"]

PREFLIGHT_CONNECT_TIMEOUT_SECONDS = 5.0
PREFLIGHT_READ_TIMEOUT_SECONDS = 10.0
PREFLIGHT_TOTAL_BUDGET_SECONDS = 15.0
# Only a short excerpt is ever used, so cap the read far below anything that could pressure a web worker.
PREFLIGHT_MAX_BODY_BYTES = 64 * 1024
BODY_EXCERPT_MAX_CHARS = 200
PREFLIGHT_CACHE_TTL_SECONDS = 300

_FRAME_ANCESTORS_RE = re.compile(r"(?:^|;)\s*frame-ancestors\s+([^;]+)", re.IGNORECASE)


@dataclass(frozen=True)
class PreflightResult:
    framing: Framing
    blocked_by: BlockedBy | None
    http_status: int | None
    body_excerpt: str | None


def _origin_parts(origin: str) -> tuple[str, str]:
    parts = urlsplit(origin)
    return parts.scheme.lower(), (parts.hostname or "").lower()


def _source_matches_origin(source: str, scheme: str, host: str) -> bool:
    source = source.strip()
    # Keyword sources are quoted ('none', 'self', 'unsafe-inline'). None of them can name the app,
    # which is always a different origin than the customer's site.
    if source.startswith("'") or source.startswith('"'):
        return False
    if not source:
        return False
    if source == "*":
        return True

    candidate = urlsplit(source if "//" in source else f"//{source}")
    source_host = (candidate.hostname or "").lower()
    source_scheme = (candidate.scheme or "").lower()
    if not source_host:
        return False
    if source_scheme and source_scheme != scheme:
        return False

    if source_host.startswith("*."):
        return host == source_host[2:] or host.endswith(f".{source_host[2:]}")
    return host == source_host


def _frame_ancestors_verdict(directive: str, scheme: str, host: str) -> Framing:
    sources = directive.split()
    if not sources:
        return "unknown"
    return "allowed" if any(_source_matches_origin(s, scheme, host) for s in sources) else "blocked"


def analyze_framing_headers(headers: dict[str, str]) -> tuple[Framing, BlockedBy | None]:
    """Decide whether the PostHog app may embed a page in an iframe, from its response headers."""
    scheme, host = _origin_parts(settings.SITE_URL)
    lowered = {k.lower(): v for k, v in headers.items()}

    # CSP frame-ancestors supersedes X-Frame-Options wherever both are present.
    csp = lowered.get("content-security-policy")
    if csp:
        match = _FRAME_ANCESTORS_RE.search(csp)
        if match:
            verdict = _frame_ancestors_verdict(match.group(1), scheme, host)
            return verdict, "frame_ancestors" if verdict == "blocked" else None

    # Neither DENY nor SAMEORIGIN can ever name the app. ALLOW-FROM is not handled because no
    # browser we support ever implemented it, and an unrecognized value is ignored by browsers,
    # so it tells us nothing.
    xfo = lowered.get("x-frame-options", "").strip().lower()
    if xfo in ("deny", "sameorigin"):
        return "blocked", "x_frame_options"

    return "allowed", None


def _body_excerpt(response: requests.Response) -> str | None:
    # The read timeout bounds the gap between chunks, not the total transfer, so a host that
    # trickles bytes indefinitely would otherwise hold a web worker and grow unboundedly.
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + PREFLIGHT_TOTAL_BUDGET_SECONDS
    for chunk in response.iter_content(chunk_size=4096):
        chunks.append(chunk)
        total += len(chunk)
        if total >= PREFLIGHT_MAX_BODY_BYTES or time.monotonic() > deadline:
            break
    text = b"".join(chunks)[:PREFLIGHT_MAX_BODY_BYTES].decode(response.encoding or "utf-8", errors="replace")
    return " ".join(text[:BODY_EXCERPT_MAX_CHARS].split()) or None


def _probe(url: str) -> PreflightResult:
    try:
        with pinned_session(url) as session:
            res = session.request(
                "GET",
                url,
                timeout=(PREFLIGHT_CONNECT_TIMEOUT_SECONDS, PREFLIGHT_READ_TIMEOUT_SECONDS),
                allow_redirects=False,
                stream=True,
            )
            if not 200 <= res.status_code < 300:
                # A redirect hides the real page's headers, and on any other non-2xx the headers
                # belong to the host's error response rather than to the page, so they say nothing
                # about framing either way. The status is the answer worth reporting.
                return PreflightResult("unknown", None, res.status_code, _body_excerpt(res))

            framing, blocked_by = analyze_framing_headers(dict(res.headers))
            return PreflightResult(framing, blocked_by, res.status_code, None)
    except SSRFBlockedError as e:
        logger.info("heatmap_preflight.url_blocked", reason=str(e))
        return PreflightResult("unknown", None, None, None)
    except requests.RequestException:
        # Deliberately not logging the exception or the URL: both routinely echo the full target,
        # and a customer-supplied URL can carry credentials or a signed token.
        logger.info("heatmap_preflight.request_failed")
        return PreflightResult("unknown", None, None, None)


def preflight_page(url: str) -> PreflightResult:
    """Explain why a page can't back a live-preview heatmap.

    Never raises for a remote-side problem: an unreachable or hostile host is an answer, not an
    error, so callers always get a verdict to show the user. Settled verdicts are cached briefly so
    repeat checks for the same page don't refetch it; an inconclusive one isn't, so a transient
    failure can be retried.
    """
    url = strip_userinfo(url)
    cache_key = f"heatmap_preflight:{sha256(url.encode()).hexdigest()}"
    cached = cache.get(cache_key)
    if isinstance(cached, PreflightResult):
        return cached

    result = _probe(url)
    if result.framing != "unknown":
        cache.set(cache_key, result, PREFLIGHT_CACHE_TTL_SECONDS)
    return result
