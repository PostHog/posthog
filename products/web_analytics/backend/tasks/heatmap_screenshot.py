import os
import re
import json
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings

import structlog
import posthoganalytics
from celery import shared_task
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

from products.web_analytics.backend.api.heatmaps_utils import DEFAULT_TARGET_WIDTHS
from products.web_analytics.backend.models import HeatmapSnapshot, SavedHeatmap

logger = structlog.get_logger(__name__)

TMP_DIR = "/tmp"

HEATMAP_BROWSERLESS_FLAG = "heatmap-browserless-cloud"


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
    # silently lost; no-ops off PostHog Cloud.
    team = screenshot.team
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
            groups={"organization": str(team.organization_id), "project": str(team.uuid)},
        )


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.EXPORTS.value,
    autoretry_for=(Exception,),
    retry_backoff=2,
    retry_backoff_max=60,
    max_retries=3,
)
def generate_heatmap_screenshot(screenshot_id: str) -> None:
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

        except Exception as e:
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
            raise


def _build_browserless_cdp_url(width: int | None = None) -> str | None:
    # Read settings at call time (not import) so override_settings works in tests.
    # Strip whitespace + any inline comment a bash-sourced .env left in the value, else a `#` is
    # parsed as a URL fragment and connect fails.
    base_url = settings.HEATMAP_BROWSERLESS_URL.split("#", 1)[0].strip()
    if not base_url:
        return None

    # Strict v2 connect rejects unknown params, so only append ones the WSS endpoint accepts.
    params = {"token": settings.HEATMAP_BROWSERLESS_TOKEN, "timeout": str(settings.HEATMAP_BROWSERLESS_TIMEOUT_MS)}
    if settings.HEATMAP_BROWSERLESS_BLOCK_ADS:
        params["blockAds"] = "true"
    if settings.HEATMAP_BROWSERLESS_BLOCK_CONSENT_MODALS:
        params["blockConsentModals"] = "true"
    if width is not None:
        # Over CDP the per-context viewport is ignored; the rendered width is fixed by the launch
        # window size, so each width launches with its own --window-size.
        params["launch"] = json.dumps(
            {"args": ["--force-device-scale-factor=1", f"--window-size={int(width)},800"]},
            separators=(",", ":"),
        )

    parts = urlsplit(base_url)
    # Preserve any query already on the base URL; our params win on key collisions.
    merged = dict(parse_qsl(parts.query, keep_blank_values=True))
    merged.update(params)
    return urlunsplit(parts._replace(query=urlencode(merged)))


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


def _connect_or_launch_browser(p: Playwright, use_browserless: bool, width: int | None = None) -> Browser:
    # Cloud path connects to Browserless over CDP; `width` sets that connection's launch window size.
    cdp_url = _build_browserless_cdp_url(width) if use_browserless else None
    if cdp_url:
        try:
            return p.chromium.connect_over_cdp(cdp_url, timeout=settings.HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS)
        except Exception as e:
            # Playwright echoes the token-bearing URL into connect errors, which this task persists to
            # SavedHeatmap.exception; re-raise scrubbed, with `from None` so the token can't leak via __context__.
            raise RuntimeError(
                f"Browserless connect failed for {_redact_browserless_url(cdp_url)}: "
                f"{_sanitize_browserless_error(str(e))}"
            ) from None

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


def _render_width(browser: Browser, width: int, url: str, is_cloud: bool) -> bytes:
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
        # Local-only: the --no-sandbox Chromium is on our network, so per-request SSRF interception is
        # load-bearing. The cloud browser is off-net, so egress containment is delegated to Browserless.
        if not is_cloud:
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
    # Closing a torn-down CDP connection can itself raise; swallow so it can't mask the render error.
    try:
        browser.close()
    except Exception:
        logger.warning("heatmap_screenshot.browser_close_failed", exc_info=True)


def _generate_screenshots(screenshot: SavedHeatmap, use_browserless: bool) -> int:
    # Determine target widths
    target_widths = screenshot.target_widths or DEFAULT_TARGET_WIDTHS
    # Deduplicate and keep order
    seen = set()
    widths: list[int] = []
    for w in target_widths:
        if isinstance(w, int) and 100 <= w <= 3000 and w not in seen:
            widths.append(w)
            seen.add(w)

    if not widths:
        widths = [1024]

    # Persist AFTER the Playwright block: ORM calls inside `with sync_playwright()` raise
    # SynchronousOnlyOperation (its greenlet/event-loop context).
    snapshot_bytes: list[tuple[int, bytes]] = []
    with sync_playwright() as p:
        if use_browserless:
            # Each width opens its own connection so it can launch at its own window size, the only
            # way to control rendered width over CDP (see _build_browserless_cdp_url).
            for w in widths:
                browser = _connect_or_launch_browser(p, use_browserless=True, width=w)
                try:
                    snapshot_bytes.append((w, _render_width(browser, w, screenshot.url, is_cloud=True)))
                finally:
                    _close_browser_quietly(browser)
        else:
            browser = _connect_or_launch_browser(p, use_browserless=False)
            try:
                for w in widths:
                    snapshot_bytes.append((w, _render_width(browser, w, screenshot.url, is_cloud=False)))
            finally:
                _close_browser_quietly(browser)

    for w, image_data in snapshot_bytes:
        snapshot, _ = HeatmapSnapshot.objects.get_or_create(heatmap=screenshot, width=w)
        snapshot.content = image_data
        snapshot.content_location = None
        snapshot.save()

    return len(snapshot_bytes)
