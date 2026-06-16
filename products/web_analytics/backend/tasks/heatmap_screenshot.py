import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings

import requests
import structlog
import posthoganalytics
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import ph_scoped_capture
from posthog.security.url_validation import is_url_allowed
from posthog.tasks.utils import CeleryQueue

from products.web_analytics.backend.api.heatmaps_utils import DEFAULT_TARGET_WIDTHS, MAX_TARGET_WIDTHS
from products.web_analytics.backend.models import HeatmapSnapshot, SavedHeatmap

logger = structlog.get_logger(__name__)

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


def _capture_mode_usage(
    screenshot: SavedHeatmap,
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
                    "mode": "browserless",
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


def _record_failure(screenshot: SavedHeatmap, e: Exception) -> None:
    screenshot.status = SavedHeatmap.Status.FAILED
    screenshot.exception = str(e)
    screenshot.save(update_fields=["status", "exception"])

    _capture_mode_usage(screenshot, success=False, error_type=type(e).__name__)

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

            started_at = time.monotonic()
            width_count = _generate_screenshots(screenshot)
            duration_seconds = round(time.monotonic() - started_at, 2)

            screenshot.status = SavedHeatmap.Status.COMPLETED
            screenshot.save()

            _capture_mode_usage(
                screenshot,
                success=True,
                width_count=width_count,
                duration_seconds=duration_seconds,
            )

            logger.info(
                "heatmap_screenshot.completed",
                screenshot_id=screenshot.id,
                team_id=screenshot.team_id,
                url=screenshot.url,
                mode="browserless",
                duration_seconds=duration_seconds,
            )

        except (BrowserlessPermanentError, SoftTimeLimitExceeded) as e:
            # Won't succeed on retry (bad request / config / oversized output / timed out) — fail now.
            _record_failure(screenshot, e)
            raise
        except Exception as e:
            # Transient Browserless failure: retry with backoff, but only record FAILED + emit the
            # failure event once retries are exhausted, so a blip doesn't flap the status or inflate
            # the failure metric.
            if self.request.called_directly or self.request.retries >= self.max_retries:
                _record_failure(screenshot, e)
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
    # Keep a plain-http scheme for in-network Browserless (e.g. hobby's http://browserless:3000);
    # anything else (https/wss/missing) goes over https.
    scheme = "http" if parsed.scheme in ("http", "ws") else "https"
    params = {"token": settings.HEATMAP_BROWSERLESS_TOKEN, "timeout": str(settings.HEATMAP_BROWSERLESS_TIMEOUT_MS)}
    return f"{scheme}://{netloc}/screenshot?{urlencode(params)}"


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
        "bestAttempt": True,
    }
    # blockConsentModals / blockAds are browserless.io cloud API extensions; the self-hosted OSS
    # image rejects unknown body fields (400 "must NOT have additional properties"), so only send
    # them when enabled.
    if settings.HEATMAP_BROWSERLESS_BLOCK_CONSENT_MODALS:
        body["blockConsentModals"] = True
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


def _generate_screenshots(screenshot: SavedHeatmap) -> int:
    widths = _resolve_widths(screenshot)
    return _generate_browserless_screenshots(screenshot, widths)


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
