from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.conf import settings

import structlog
from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from posthog.storage import object_storage

logger = structlog.get_logger(__name__)

# How long a presigned content URL stays valid. Short — the asset viewer fetches
# it immediately on open.
CONTENT_URL_EXPIRY_SECONDS = 60


class BrowserlessUnavailable(Exception):
    """Raised when PDF rendering can't reach the browserless service."""


def presigned_content_url(s3_key: str) -> Optional[str]:
    """A short-lived presigned GET URL for the rendered email HTML, served inline."""
    return object_storage.get_presigned_url(
        s3_key,
        expiration=CONTENT_URL_EXPIRY_SECONDS,
        content_type="text/html; charset=utf-8",
        content_disposition="inline",
    )


def read_html(s3_key: str) -> Optional[bytes]:
    return object_storage.read_bytes(s3_key, missing_ok=True)


def _build_cdp_endpoint(cdp_url: str, token: str, session_timeout_ms: int) -> str:
    parsed = urlparse(cdp_url)
    query = {
        key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key not in ("token", "timeout")
    }
    if token:
        query["token"] = token
    query["timeout"] = str(session_timeout_ms)
    return urlunparse(parsed._replace(query=urlencode(query)))


def render_html_to_pdf(html: bytes) -> bytes:
    """Render an email's HTML snapshot to a PDF via the browserless service.

    On demand only — we never render at send time. Raises BrowserlessUnavailable
    when the service isn't configured or reachable so the caller can return a 503.
    """
    if not settings.BROWSERLESS_CDP_URL:
        raise BrowserlessUnavailable(
            "BROWSERLESS_CDP_URL is not set. PDF export renders via a browserless service and cannot run without it."
        )

    endpoint = _build_cdp_endpoint(
        settings.BROWSERLESS_CDP_URL, settings.BROWSERLESS_TOKEN, settings.BROWSERLESS_SESSION_TIMEOUT_MS
    )

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(endpoint, timeout=settings.BROWSERLESS_CONNECT_TIMEOUT_MS)
        except (PlaywrightError, PlaywrightTimeoutError) as e:
            raise BrowserlessUnavailable("Failed to connect to browserless for PDF render") from e

        context = None
        try:
            context = browser.new_context()
            page = context.new_page()
            # Wait for `load` (DOM + same-document resources), not `networkidle`: an email
            # referencing a slow/unreachable image CDN must not pin the Playwright session
            # (and the worker behind it) for the full timeout. Remote images still resolve
            # during page.pdf(). Bounded at 15s to cap the blast radius under concurrency.
            page.set_content(html.decode("utf-8", errors="replace"), wait_until="load", timeout=15000)
            return page.pdf(print_background=True, format="A4")
        finally:
            if context is not None:
                context.close()
            browser.close()
