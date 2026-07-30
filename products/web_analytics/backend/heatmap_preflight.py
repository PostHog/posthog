import re
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from urllib.parse import SplitResult, urljoin, urlsplit

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
PREFLIGHT_MAX_REDIRECTS = 5

_FRAME_ANCESTORS_RE = re.compile(r"(?:^|;)\s*frame-ancestors\s+([^;]+)", re.IGNORECASE)
_SCHEME_SOURCE_RE = re.compile(r"^[a-z][a-z0-9+.\-]*:$")
_DEFAULT_PORTS = {"http": 80, "https": 443}
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class PreflightResult:
    framing: Framing
    blocked_by: BlockedBy | None
    http_status: int | None
    body_excerpt: str | None


# Carries no status on purpose: the UI reads a status as the host's own answer about the page, and
# a status from a hop that never resolved into a page is not that.
_INCONCLUSIVE = PreflightResult("unknown", None, None, None)


def _effective_port(parts: SplitResult, scheme: str) -> int | None:
    try:
        port = parts.port
    except ValueError:
        return None
    return port or _DEFAULT_PORTS.get(scheme)


def _origin_parts(origin: str) -> tuple[str, str, int | None]:
    parts = urlsplit(origin)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or "").lower(), _effective_port(parts, scheme)


def _source_matches_origin(source: str, scheme: str, host: str, port: int | None) -> bool:
    source = source.strip().lower()
    # Keyword sources are quoted ('none', 'self', 'unsafe-inline'). None of them can name the app,
    # which is always a different origin than the customer's site.
    if source.startswith("'") or source.startswith('"'):
        return False
    if not source:
        return False
    if source == "*":
        return True
    # A scheme-source ("https:") allows every origin on that scheme.
    if _SCHEME_SOURCE_RE.match(source):
        return source[:-1] == scheme

    any_port = source.endswith(":*")
    authority = source[:-2] if any_port else source
    candidate = urlsplit(authority if "//" in authority else f"//{authority}")
    source_host = (candidate.hostname or "").lower()
    source_scheme = (candidate.scheme or "").lower()
    if not source_host:
        return False
    if source_scheme and source_scheme != scheme:
        return False
    # A source with no port means that scheme's default port, so one naming a different port is a
    # different origin to the browser even when the host matches.
    if not any_port and _effective_port(candidate, source_scheme or scheme) != port:
        return False

    if source_host.startswith("*."):
        return host == source_host[2:] or host.endswith(f".{source_host[2:]}")
    return host == source_host


def _frame_ancestors_verdict(directive: str, scheme: str, host: str, port: int | None) -> Framing:
    sources = directive.split()
    if not sources:
        return "unknown"
    return "allowed" if any(_source_matches_origin(s, scheme, host, port) for s in sources) else "blocked"


def analyze_framing_headers(headers: dict[str, str]) -> tuple[Framing, BlockedBy | None]:
    """Decide whether the PostHog app may embed a page in an iframe, from its response headers."""
    scheme, host, port = _origin_parts(settings.SITE_URL)
    lowered = {k.lower(): v for k, v in headers.items()}

    # CSP frame-ancestors supersedes X-Frame-Options wherever both are present. A response can carry
    # more than one policy, either comma-separated or as repeated headers that requests joins the
    # same way, and each applies on its own, so any one of them blocking is decisive.
    csp = lowered.get("content-security-policy")
    if csp:
        verdicts: list[Framing] = []
        for policy in csp.split(","):
            match = _FRAME_ANCESTORS_RE.search(policy)
            if match:
                verdicts.append(_frame_ancestors_verdict(match.group(1), scheme, host, port))
        if "blocked" in verdicts:
            return "blocked", "frame_ancestors"
        if verdicts:
            return ("allowed", None) if all(v == "allowed" for v in verdicts) else ("unknown", None)

    # Neither DENY nor SAMEORIGIN can ever name the app. ALLOW-FROM is not handled because no
    # browser we support ever implemented it, and an unrecognized value is ignored by browsers,
    # so it tells us nothing.
    xfo = lowered.get("x-frame-options", "").strip().lower()
    if xfo in ("deny", "sameorigin"):
        return "blocked", "x_frame_options"

    return "allowed", None


def _body_excerpt(response: requests.Response, deadline: float) -> str | None:
    # The read timeout bounds the gap between chunks, not the total transfer, so a host that
    # trickles bytes indefinitely would otherwise hold a web worker and grow unboundedly.
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=4096):
        chunks.append(chunk)
        total += len(chunk)
        if total >= PREFLIGHT_MAX_BODY_BYTES or time.monotonic() > deadline:
            break
    text = b"".join(chunks)[:PREFLIGHT_MAX_BODY_BYTES].decode(response.encoding or "utf-8", errors="replace")
    return " ".join(text[:BODY_EXCERPT_MAX_CHARS].split()) or None


def _probe(url: str) -> PreflightResult:
    # One budget for the whole chain, so following a redirect can't multiply how long a web worker
    # is held.
    deadline = time.monotonic() + PREFLIGHT_TOTAL_BUDGET_SECONDS
    current = url

    for _ in range(PREFLIGHT_MAX_REDIRECTS + 1):
        read_timeout = min(PREFLIGHT_READ_TIMEOUT_SECONDS, deadline - time.monotonic())
        if read_timeout <= 0:
            return _INCONCLUSIVE
        try:
            with pinned_session(current) as session:
                res = session.request(
                    "GET",
                    current,
                    timeout=(PREFLIGHT_CONNECT_TIMEOUT_SECONDS, read_timeout),
                    allow_redirects=False,
                    stream=True,
                )
                if 200 <= res.status_code < 300:
                    framing, blocked_by = analyze_framing_headers(dict(res.headers))
                    return PreflightResult(framing, blocked_by, res.status_code, None)

                if res.status_code in _REDIRECT_STATUSES:
                    location = res.headers.get("location")
                    if not location:
                        return _INCONCLUSIVE
                    # An iframe follows redirects too, so the page that decides framing is the one
                    # at the end of the chain, and reporting the 3xx instead would accuse a healthy
                    # host of failing. Re-entering pinned_session per hop is what keeps every target
                    # SSRF-validated and pinned to the address it was validated against.
                    current = strip_userinfo(urljoin(current, location))
                    continue

                # The headers on any other non-2xx belong to the host's error response rather than
                # to the page, so they say nothing about framing either way. The status is the
                # answer worth reporting.
                return PreflightResult("unknown", None, res.status_code, _body_excerpt(res, deadline))
        except SSRFBlockedError as e:
            logger.info("heatmap_preflight.url_blocked", reason=str(e))
            return _INCONCLUSIVE
        except requests.RequestException:
            # Deliberately not logging the exception or the URL: both routinely echo the full target,
            # and a customer-supplied URL can carry credentials or a signed token.
            logger.info("heatmap_preflight.request_failed")
            return _INCONCLUSIVE

    return _INCONCLUSIVE


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
