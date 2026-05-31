import os
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings

import requests
import structlog
import posthoganalytics
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from playwright.sync_api import (
    Browser,
    Page,
    Playwright,
    ProxySettings,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import ph_scoped_capture
from posthog.security.url_validation import is_url_allowed, should_block_url
from posthog.tasks.utils import CeleryQueue

from products.web_analytics.backend.api.heatmaps_utils import DEFAULT_TARGET_WIDTHS, MAX_TARGET_WIDTHS
from products.web_analytics.backend.models import HeatmapSnapshot, SavedHeatmap

logger = structlog.get_logger(__name__)

TMP_DIR = "/tmp"

HEATMAP_BROWSERLESS_FLAG = "heatmap-browserless-cloud"

# Reclaim a hung worker rather than letting a stuck render hold an EXPORTS slot for the full retry budget.
HEATMAP_SCREENSHOT_SOFT_TIME_LIMIT = 600  # seconds
HEATMAP_SCREENSHOT_TIME_LIMIT = HEATMAP_SCREENSHOT_SOFT_TIME_LIMIT + 30
# Reject implausibly large Browserless responses before they reach worker memory / Postgres.
HEATMAP_SCREENSHOT_MAX_BYTES = 20 * 1024 * 1024


class BrowserlessError(Exception):
    """Base class for Browserless /screenshot failures."""


class BrowserlessTransientError(BrowserlessError):
    """A failure that may succeed on retry (5xx, timeout, empty/blank render)."""


class BrowserlessPermanentError(BrowserlessError):
    """A failure that will not be fixed by retrying (4xx, misconfiguration, oversized output)."""


def _dismiss_cookie_banners(page: Page) -> None:
    # Try to click obvious accept/allow buttons (generic + Cookiebot)
    click_selectors = [
        # Generic
        'button:has-text("Accept")',
        'button:has-text("I Agree")',
        'button:has-text("I agree")',
        'button:has-text("Got it")',
        'button:has-text("OK")',
        'button[aria-label*="accept" i]',
        '[role="dialog"] button:has-text("Accept")',
        'button[id*="accept" i], button[class*="accept" i]',
        # OneTrust
        "#onetrust-accept-btn-handler",
        ".onetrust-accept-btn-handler",
        # Cookiebot specific
        "#CybotCookiebotDialogBodyButtonAccept",
        "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    ]
    for sel in click_selectors:
        try:
            el = page.locator(sel).first
            # wait a short time for element to appear, then click
            el.wait_for(timeout=500)
            el.click(timeout=500)
            page.wait_for_timeout(250)
            break
        except Exception:
            pass

    # CSS-hide common cookie/consent containers and overlays
    # Important: Only target specific container elements (div, section, aside, etc.) to avoid hiding html/body
    # which may have cookie-related classes (e.g., <html class="supports-no-cookies">)
    css_hide = """
    div[id*="cookie" i], div[class*="cookie" i],
    div[id*="consent" i], div[class*="consent" i],
    div[id*="gdpr" i], div[class*="gdpr" i],
    div[id*="onetrust" i], div[class*="onetrust" i],
    div[id*="ot-sdk" i], div[class*="ot-sdk" i],
    div[id*="sp_message" i], div[class*="sp_message" i],
    div[id*="sp-consent" i], div[class*="sp-consent" i],
    div[id*="quantcast" i], div[class*="quantcast" i],
    section[id*="cookie" i], section[class*="cookie" i],
    section[id*="consent" i], section[class*="consent" i],
    section[id*="gdpr" i], section[class*="gdpr" i],
    section[id*="onetrust" i], section[class*="onetrust" i],
    section[id*="ot-sdk" i], section[class*="ot-sdk" i],
    section[id*="sp_message" i], section[class*="sp_message" i],
    section[id*="sp-consent" i], section[class*="sp-consent" i],
    section[id*="quantcast" i], section[class*="quantcast" i],
    aside[id*="cookie" i], aside[class*="cookie" i],
    aside[id*="consent" i], aside[class*="consent" i],
    aside[id*="gdpr" i], aside[class*="gdpr" i],
    aside[id*="onetrust" i], aside[class*="onetrust" i],
    aside[id*="ot-sdk" i], aside[class*="ot-sdk" i],
    aside[id*="sp_message" i], aside[class*="sp_message" i],
    aside[id*="sp-consent" i], aside[class*="sp-consent" i],
    aside[id*="quantcast" i], aside[class*="quantcast" i],
    iframe[src*="consent" i], iframe[src*="cookie" i], iframe[src*="onetrust" i],
    /* generic fixed overlays */
    div[style*="position:fixed" i][style*="z-index" i] {
        display: none !important;
        visibility: hidden !important;
        pointer-events: none !important;
    }
    """
    try:
        page.add_style_tag(content=css_hide)
    except Exception:
        pass

    # Explicitly remove Cookiebot dialog + underlay if present (add here more specific selectors if needed)
    try:
        page.evaluate(
            """
            () => {
              document.getElementById('CybotCookiebotDialog')?.remove();
              document.getElementById('CybotCookiebotDialogBodyUnderlay')?.remove();
            }
            """
        )
    except Exception:
        pass


def _block_internal_requests(page: Page) -> None:
    page.route("**/*", lambda route: route.abort() if should_block_url(route.request.url) else route.continue_())


def _scroll_page(page: Page) -> None:
    """
    Scroll to bottom and back to top to trigger lazy-loaded content and CSS.

    Some sites lazy-load CSS, images, or other content as you scroll.
    Scrolling through the page ensures everything is loaded before screenshot.
    Uses smooth, human-like scrolling to avoid triggering scroll-based hiding.
    """
    try:
        page.evaluate(
            """
            async () => {
                // Smooth scroll function (more human-like)
                const smoothScroll = (target) => {
                    return new Promise(resolve => {
                        window.scrollTo({
                            top: target,
                            behavior: 'smooth'
                        });
                        // Wait for smooth scroll to finish
                        setTimeout(resolve, 500);
                    });
                };

                const step = window.innerHeight * 0.7;
                let maxScroll = document.body.scrollHeight;
                const maxIterations = 5; // ~3 viewport heights max
                let iterations = 0;

                // Scroll down slowly (just enough to trigger lazy loading)
                for (let y = 0; y < maxScroll && iterations < maxIterations; y += step) {
                    await smoothScroll(y);
                    await new Promise(r => setTimeout(r, 300));
                    // Re-measure as images load and page expands
                    maxScroll = Math.max(maxScroll, document.body.scrollHeight);
                    iterations++;
                }

                // Scroll to absolute bottom
                await smoothScroll(maxScroll);
                await new Promise(r => setTimeout(r, 500));

                // Scroll back to top slowly
                await smoothScroll(0);
                await new Promise(r => setTimeout(r, 500));
            }
            """
        )
        page.wait_for_timeout(500)
    except Exception:
        pass


def _capture_mode_usage(
    screenshot: SavedHeatmap,
    use_browserless: bool,
    *,
    success: bool,
    width_count: int | None = None,
    duration_seconds: float | None = None,
    error_type: str | None = None,
) -> None:
    # ph_scoped_capture (not posthoganalytics.capture) — events from Celery tasks are otherwise
    # silently lost; no-ops off PostHog Cloud. Telemetry must never fail the task, so swallow errors.
    team = screenshot.team
    try:
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=str(team.uuid),
                event="heatmap screenshot generated",
                properties={
                    "mode": "browserless" if use_browserless else "local",
                    "success": success,
                    "width_count": width_count,
                    "duration_seconds": duration_seconds,
                    "error_type": error_type,
                    "team_id": team.id,
                    "screenshot_id": str(screenshot.id),
                },
                groups={"organization": str(team.organization_id), "project": str(team.id)},
            )
    except Exception:
        logger.warning("heatmap_screenshot.usage_capture_failed", screenshot_id=screenshot.id, exc_info=True)


def _record_failure(screenshot: SavedHeatmap, use_browserless: bool, e: Exception) -> None:
    screenshot.status = SavedHeatmap.Status.FAILED
    screenshot.exception = str(e)
    screenshot.save(update_fields=["status", "exception"])

    _capture_mode_usage(screenshot, use_browserless, success=False, error_type=type(e).__name__)

    logger.exception(
        "heatmap_screenshot.failed",
        screenshot_id=screenshot.id,
        team_id=screenshot.team_id,
        url=screenshot.url,
        exception=str(e),
        exc_info=True,
    )

    capture_exception(
        e,
        additional_properties={
            "celery_task": "heatmap_screenshot",
            "team_id": screenshot.team_id,
            "screenshot_id": screenshot.id,
        },
    )


@shared_task(
    bind=True,
    ignore_result=True,
    queue=CeleryQueue.EXPORTS.value,
    max_retries=3,
    soft_time_limit=HEATMAP_SCREENSHOT_SOFT_TIME_LIMIT,
    time_limit=HEATMAP_SCREENSHOT_TIME_LIMIT,
)
def generate_heatmap_screenshot(self: Task, screenshot_id: str) -> None:
    try:
        screenshot = SavedHeatmap.objects.select_related("team", "created_by").get(id=screenshot_id)
    except SavedHeatmap.DoesNotExist:
        logger.exception("heatmap_screenshot.not_found", screenshot_id=screenshot_id)
        return

    with posthoganalytics.new_context():
        posthoganalytics.tag("team_id", screenshot.team_id)
        posthoganalytics.tag("screenshot_id", screenshot.id)

        use_browserless = False
        try:
            ok, err = is_url_allowed(screenshot.url)
            if not ok:
                screenshot.status = SavedHeatmap.Status.FAILED
                screenshot.exception = f"SSRF blocked: {err}"
                screenshot.save(update_fields=["status", "exception"])
                logger.warning(
                    "heatmap_screenshot.ssrf_blocked",
                    screenshot_id=screenshot.id,
                    team_id=screenshot.team_id,
                    url=screenshot.url,
                    reason=err,
                )
                return

            use_browserless = _use_browserless_for_screenshot(screenshot)
            posthoganalytics.tag("use_browserless", use_browserless)

            started_at = time.monotonic()
            width_count = _generate_screenshots(screenshot, use_browserless)
            duration_seconds = round(time.monotonic() - started_at, 2)

            screenshot.status = SavedHeatmap.Status.COMPLETED
            screenshot.save()

            _capture_mode_usage(
                screenshot,
                use_browserless,
                success=True,
                width_count=width_count,
                duration_seconds=duration_seconds,
            )

            logger.info(
                "heatmap_screenshot.completed",
                screenshot_id=screenshot.id,
                team_id=screenshot.team_id,
                url=screenshot.url,
                mode="browserless" if use_browserless else "local",
                duration_seconds=duration_seconds,
            )

        except (BrowserlessPermanentError, SoftTimeLimitExceeded) as e:
            # Won't succeed on retry (bad request / config / oversized output / timed out) — fail now.
            _record_failure(screenshot, use_browserless, e)
            raise
        except Exception as e:
            # Transient cloud failure or a local render error: retry with backoff, but only record
            # FAILED + emit the failure event once retries are exhausted, so a blip doesn't flap the
            # status or inflate the failure metric.
            if self.request.called_directly or self.request.retries >= self.max_retries:
                _record_failure(screenshot, use_browserless, e)
                raise
            logger.warning(
                "heatmap_screenshot.retrying",
                screenshot_id=screenshot.id,
                retries=self.request.retries,
                exception=str(e),
            )
            raise self.retry(exc=e, countdown=min(2 ** (self.request.retries + 1), 60))


def _build_browserless_screenshot_url() -> str | None:
    # Read settings at call time (not import) so override_settings works in tests.
    # Strip whitespace + any inline comment a bash-sourced .env left in the value.
    base_url = settings.HEATMAP_BROWSERLESS_URL.split("#", 1)[0].strip()
    parsed = urlsplit(base_url) if base_url else None
    host = parsed.hostname if parsed else None
    if not parsed or not host:
        return None
    # Preserve a non-default port so self-hosted / local Browserless (e.g. wss://host:3000/chromium) works.
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    params = {"token": settings.HEATMAP_BROWSERLESS_TOKEN, "timeout": str(settings.HEATMAP_BROWSERLESS_TIMEOUT_MS)}
    return f"https://{netloc}/screenshot?{urlencode(params)}"


def _redact_browserless_url(url: str) -> str:
    # Strip userinfo and the token value so the URL is safe to put in errors/logs.
    parts = urlsplit(url)
    safe_query = urlencode(
        [(k, "REDACTED" if k == "token" else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    )
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc, query=safe_query))


_TOKEN_QS_RE = re.compile(r"(token=)[^&\s\"']+")


def _sanitize_browserless_error(message: str) -> str:
    # Scrub the token (raw value + any `token=...` in an echoed URL) while keeping the error reason.
    token = settings.HEATMAP_BROWSERLESS_TOKEN
    if token:
        message = message.replace(token, "REDACTED")
    return _TOKEN_QS_RE.sub(r"\1REDACTED", message)


def _is_permanent_status(status: int) -> bool:
    # 4xx won't be fixed by retrying, except request-timeout / rate-limit which are worth a retry.
    return 400 <= status < 500 and status not in (408, 429)


def _validate_screenshot_response(response: requests.Response, endpoint_url: str) -> bytes:
    # A 200 from Browserless isn't necessarily a usable JPEG: bestAttempt can return a blank/partial
    # render, and errors can come back as a 200 with a JSON/text body. Reject anything that isn't a
    # sane image before it's stored and served as image/jpeg.
    content = response.content
    if len(content) > HEATMAP_SCREENSHOT_MAX_BYTES:
        raise BrowserlessPermanentError(
            f"Browserless screenshot too large ({len(content)} bytes) for {_redact_browserless_url(endpoint_url)}"
        )
    if not content:
        raise BrowserlessTransientError(
            f"Browserless returned an empty body for {_redact_browserless_url(endpoint_url)}"
        )
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        raise BrowserlessTransientError(
            f"Browserless returned non-image content-type {content_type!r} for "
            f"{_redact_browserless_url(endpoint_url)}: {_sanitize_browserless_error(response.text[:200])}"
        )
    if not content.startswith(b"\xff\xd8\xff"):  # JPEG start-of-image marker
        raise BrowserlessTransientError(
            f"Browserless returned a non-JPEG body for {_redact_browserless_url(endpoint_url)}"
        )
    return content


def _browserless_screenshot(endpoint_url: str, page_url: str, width: int) -> bytes:
    # Render one width via the Browserless /screenshot REST API. viewport.width sets the captured width;
    # scrollPage triggers lazy-loaded content and blockConsentModals dismisses cookie banners server-side.
    body: dict[str, object] = {
        "url": page_url,
        "options": {"fullPage": True, "type": "jpeg", "quality": 70},
        "viewport": {
            "width": int(width),
            "height": 800,
            "deviceScaleFactor": 1,
            "isMobile": width < 500,
            "hasTouch": width < 500,
        },
        "gotoOptions": {"waitUntil": "networkidle2", "timeout": 30_000},
        "scrollPage": True,
        "blockConsentModals": settings.HEATMAP_BROWSERLESS_BLOCK_CONSENT_MODALS,
        "bestAttempt": True,
    }
    if settings.HEATMAP_BROWSERLESS_BLOCK_ADS:
        body["blockAds"] = True

    timeout = (
        settings.HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS / 1000,
        settings.HEATMAP_BROWSERLESS_TIMEOUT_MS / 1000 + 30,
    )
    try:
        response = requests.post(endpoint_url, json=body, timeout=timeout)
    except Exception as e:
        # The endpoint URL carries the token; scrub it before it reaches logs / SavedHeatmap.exception.
        raise BrowserlessTransientError(
            f"Browserless screenshot request failed for {_redact_browserless_url(endpoint_url)}: "
            f"{_sanitize_browserless_error(str(e))}"
        ) from None
    if response.status_code != 200:
        message = (
            f"Browserless screenshot failed ({response.status_code}) for "
            f"{_redact_browserless_url(endpoint_url)}: {_sanitize_browserless_error(response.text[:500])}"
        )
        if _is_permanent_status(response.status_code):
            raise BrowserlessPermanentError(message)
        raise BrowserlessTransientError(message)
    return _validate_screenshot_response(response, endpoint_url)


def _use_browserless_for_screenshot(screenshot: SavedHeatmap) -> bool:
    # Gated per team in prod; in local dev (DEBUG) the env var alone is the switch. Fail closed to
    # the local launch on any flag-eval error.
    if not settings.HEATMAP_BROWSERLESS_URL:
        return False
    if settings.DEBUG:
        return True

    team = screenshot.team
    org_id = str(team.organization_id)
    project_id = str(team.id)
    try:
        return bool(
            posthoganalytics.feature_enabled(
                HEATMAP_BROWSERLESS_FLAG,
                project_id,  # bucket per team so a whole team flips together, not per user
                groups={"organization": org_id, "project": project_id},
                group_properties={"organization": {"id": org_id}, "project": {"id": project_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False


def _launch_local_browser(p: Playwright) -> Browser:
    launch_args = [
        "--force-device-scale-factor=1",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--disable-gpu",
    ]
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    proxy_config = ProxySettings(server=proxy_url) if proxy_url else None
    return p.chromium.launch(
        headless=True,  # TIP: for debugging, set to False
        args=launch_args,
        proxy=proxy_config,
    )


def _render_width(browser: Browser, width: int, url: str) -> bytes:
    ctx = browser.new_context(
        viewport={"width": int(width), "height": 800},
        device_scale_factor=1,  # keep 1:1 CSS px -> bitmap px
        is_mobile=(width < 500),  # trigger mobile layout on small widths
        has_touch=(width < 500),  # some sites key on touch capability
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/115.0.0.0 "
            "Mobile/15E148 Safari/604.1"
            if width < 500
            else None
        ),
    )
    try:
        page = ctx.new_page()
        # The local --no-sandbox Chromium is on our network, so per-request SSRF interception stays.
        _block_internal_requests(page)

        # Start navigation and try to wait for DOM ready, but only up to 5s
        dom_ready = True
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=5_000)
        except PlaywrightTimeoutError:
            dom_ready = False
            # Navigation may still continue in the background; we just won't block on it.

        # Small settle: if DOM was ready, give JS time to render (SPAs). Otherwise, brief paint time.
        page.wait_for_timeout(3000 if dom_ready else 1000)

        # Try to clear overlays/cookie banners if present
        _dismiss_cookie_banners(page)
        page.wait_for_timeout(500)

        # Scroll to bottom and back to top to trigger lazy-loaded content
        _scroll_page(page)

        # Hide scrollbars so they don't appear in the exported image
        try:
            page.add_style_tag(
                content="*::-webkit-scrollbar { display: none !important; } html, body { scrollbar-width: none !important; }"
            )
        except Exception:
            pass

        return page.screenshot(full_page=True, type="jpeg", quality=70)
    finally:
        ctx.close()


def _close_browser_quietly(browser: Browser) -> None:
    # Closing an already-torn-down browser can itself raise; swallow so it can't mask the render error.
    try:
        browser.close()
    except Exception:
        logger.warning("heatmap_screenshot.browser_close_failed", exc_info=True)


def _resolve_widths(screenshot: SavedHeatmap) -> list[int]:
    target_widths = screenshot.target_widths or DEFAULT_TARGET_WIDTHS
    seen: set[int] = set()
    widths: list[int] = []
    for w in target_widths:
        if isinstance(w, int) and 100 <= w <= 3000 and w not in seen:
            widths.append(w)
            seen.add(w)
    if not widths:
        return [1024]
    # Backstop the per-width render fan-out for heatmaps created before the serializer cap (or via the
    # regenerate path), so one heatmap can't spawn an unbounded number of Browserless sessions.
    return widths[:MAX_TARGET_WIDTHS]


def _persist_snapshot(screenshot: SavedHeatmap, width: int, image_data: bytes) -> None:
    snapshot, _ = HeatmapSnapshot.objects.get_or_create(heatmap=screenshot, width=width)
    snapshot.content = image_data
    snapshot.content_location = None
    snapshot.save()


def _generate_screenshots(screenshot: SavedHeatmap, use_browserless: bool) -> int:
    widths = _resolve_widths(screenshot)
    if use_browserless:
        return _generate_browserless_screenshots(screenshot, widths)
    return _generate_local_screenshots(screenshot, widths)


def _generate_browserless_screenshots(screenshot: SavedHeatmap, widths: list[int]) -> int:
    # REST /screenshot: one request per width (viewport.width sets the captured width). Persist and
    # release each image as it arrives so worker memory holds one full-page JPEG at a time.
    endpoint_url = _build_browserless_screenshot_url()
    if not endpoint_url:
        raise BrowserlessPermanentError("Browserless screenshot URL is not configured")
    count = 0
    for w in widths:
        image_data = _browserless_screenshot(endpoint_url, screenshot.url, w)
        _persist_snapshot(screenshot, w, image_data)
        count += 1
    return count


def _generate_local_screenshots(screenshot: SavedHeatmap, widths: list[int]) -> int:
    # Local Chromium: one launch renders every width. ORM must run after the Playwright block — calls
    # inside `with sync_playwright()` raise SynchronousOnlyOperation (its event-loop context).
    snapshot_bytes: list[tuple[int, bytes]] = []
    with sync_playwright() as p:
        browser = _launch_local_browser(p)
        try:
            for w in widths:
                snapshot_bytes.append((w, _render_width(browser, w, screenshot.url)))
        finally:
            _close_browser_quietly(browser)

    for w, image_data in snapshot_bytes:
        _persist_snapshot(screenshot, w, image_data)
    return len(snapshot_bytes)
