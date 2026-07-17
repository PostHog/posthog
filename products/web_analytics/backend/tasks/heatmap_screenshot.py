import re
import time
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.utils import timezone

import requests
import structlog
import posthoganalytics
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from prometheus_client import Counter, Gauge, Histogram

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import ph_scoped_capture
from posthog.scoping_audit import skip_team_scope_audit
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
HEATMAP_SCREENSHOT_STUCK_THRESHOLD_SECONDS = HEATMAP_SCREENSHOT_TIME_LIMIT + 60
HEATMAP_SCREENSHOT_STUCK_SAMPLE_SIZE = 20

HEATMAP_SCREENSHOT_SUCCEEDED = Counter(
    "heatmap_screenshot_task_succeeded",
    "A heatmap screenshot task succeeded",
)
HEATMAP_SCREENSHOT_FAILED = Counter(
    "heatmap_screenshot_task_failed",
    "A heatmap screenshot task failed",
    labelnames=["failure_type"],
)
HEATMAP_SCREENSHOT_TIMER = Histogram(
    "heatmap_screenshot_task_duration_seconds",
    "End-to-end heatmap screenshot render time",
    labelnames=["outcome"],
    buckets=(1, 5, 10, 30, 60, 120, 240, 300, 360, 420, 480, 540, 600, float("inf")),
)
HEATMAP_BROWSERLESS_REQUEST_SECONDS = Histogram(
    "heatmap_screenshot_browserless_request_duration_seconds",
    "Latency of a single Browserless /screenshot call",
    labelnames=["outcome", "width_bucket"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, float("inf")),
)
HEATMAP_SCREENSHOT_STUCK_PROCESSING = Gauge(
    "heatmap_screenshot_stuck_processing",
    "Screenshot heatmaps still processing past the task time limit",
)


class BrowserlessError(Exception):
    """Base class for Browserless /screenshot failures."""

    def __init__(self, message: str, *, status_code: int | None = None, cause: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.cause = cause


class BrowserlessTransientError(BrowserlessError):
    """A failure that may succeed on retry (5xx, timeout, empty/blank render)."""


class BrowserlessPermanentError(BrowserlessError):
    """A failure that will not be fixed by retrying (4xx, misconfiguration, oversized output)."""


def _width_bucket(width: int) -> str:
    if width < 500:
        return "mobile"
    if width < 900:
        return "tablet"
    if width < 1440:
        return "desktop"
    return "wide"


def _classify_failure(e: BaseException) -> str:
    if isinstance(e, SoftTimeLimitExceeded):
        return "soft_time_limit"
    if isinstance(e, BrowserlessError):
        if e.cause == "not_configured":
            return "not_configured"
        if e.cause in ("empty_body", "non_image", "non_jpeg", "oversized"):
            return "validation_error"
        if e.cause == "request_exception":
            return "browserless_timeout"
        if e.status_code is not None:
            if e.status_code == 408:
                return "browserless_timeout"
            if 400 <= e.status_code < 500:
                return "browserless_4xx"
            if e.status_code >= 500:
                return "browserless_5xx"
    return "unknown"


def _capture_mode_usage(
    screenshot: SavedHeatmap,
    *,
    success: bool,
    width_count: int | None = None,
    duration_seconds: float | None = None,
    error_type: str | None = None,
    failure_type: str | None = None,
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
                    "failure_type": failure_type,
                    "team_id": team.id,
                    "screenshot_id": str(screenshot.id),
                },
                groups={"organization": str(team.organization_id), "project": str(team.id)},
            )
    except Exception:
        logger.warning("heatmap_screenshot.usage_capture_failed", screenshot_id=screenshot.id, exc_info=True)


def _record_failure(screenshot: SavedHeatmap, e: Exception, *, started_at: float | None = None) -> None:
    failure_type = _classify_failure(e)
    screenshot.status = SavedHeatmap.Status.FAILED
    screenshot.exception = str(e)
    screenshot.save(update_fields=["status", "exception"])

    HEATMAP_SCREENSHOT_FAILED.labels(failure_type=failure_type).inc()
    if started_at is not None:
        HEATMAP_SCREENSHOT_TIMER.labels(outcome="failed").observe(time.monotonic() - started_at)

    _capture_mode_usage(screenshot, success=False, error_type=type(e).__name__, failure_type=failure_type)

    logger.exception(
        "heatmap_screenshot.failed",
        screenshot_id=screenshot.id,
        team_id=screenshot.team_id,
        url=screenshot.url,
        failure_type=failure_type,
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

    queue_wait_seconds = max((timezone.now() - screenshot.updated_at).total_seconds(), 0.0)
    logger.info(
        "heatmap_screenshot.started",
        screenshot_id=screenshot.id,
        team_id=screenshot.team_id,
        url=screenshot.url,
        retries=self.request.retries,
        task_id=self.request.id,
        queue_wait_seconds=round(queue_wait_seconds, 2),
    )

    started_at = time.monotonic()
    with posthoganalytics.new_context():
        posthoganalytics.tag("team_id", screenshot.team_id)
        posthoganalytics.tag("screenshot_id", screenshot.id)

        try:
            ok, err = is_url_allowed(screenshot.url)
            if not ok:
                screenshot.status = SavedHeatmap.Status.FAILED
                screenshot.exception = f"SSRF blocked: {err}"
                screenshot.save(update_fields=["status", "exception"])
                HEATMAP_SCREENSHOT_FAILED.labels(failure_type="ssrf_blocked").inc()
                HEATMAP_SCREENSHOT_TIMER.labels(outcome="failed").observe(time.monotonic() - started_at)
                logger.warning(
                    "heatmap_screenshot.ssrf_blocked",
                    screenshot_id=screenshot.id,
                    team_id=screenshot.team_id,
                    url=screenshot.url,
                    reason=err,
                )
                return

            width_count = _generate_screenshots(screenshot)
            duration_seconds = round(time.monotonic() - started_at, 2)

            screenshot.status = SavedHeatmap.Status.COMPLETED
            screenshot.save()

            HEATMAP_SCREENSHOT_SUCCEEDED.inc()
            HEATMAP_SCREENSHOT_TIMER.labels(outcome="succeeded").observe(duration_seconds)

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
                width_count=width_count,
                duration_seconds=duration_seconds,
            )

        except (BrowserlessPermanentError, SoftTimeLimitExceeded) as e:
            # Won't succeed on retry (bad request / config / oversized output / timed out) — fail now.
            _record_failure(screenshot, e, started_at=started_at)
            raise
        except Exception as e:
            # Transient Browserless failure: retry with backoff, but only record FAILED + emit the
            # failure event once retries are exhausted, so a blip doesn't flap the status or inflate
            # the failure metric.
            if self.request.called_directly or self.request.retries >= self.max_retries:
                _record_failure(screenshot, e, started_at=started_at)
                raise
            countdown = min(2 ** (self.request.retries + 1), 60)
            logger.warning(
                "heatmap_screenshot.retrying",
                screenshot_id=screenshot.id,
                team_id=screenshot.team_id,
                url=screenshot.url,
                retries=self.request.retries,
                max_retries=self.max_retries,
                countdown=countdown,
                failure_type=_classify_failure(e),
                exception=str(e),
            )
            raise self.retry(exc=e, countdown=countdown)


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
            f"Browserless screenshot too large ({len(content)} bytes) for {_redact_browserless_url(endpoint_url)}",
            cause="oversized",
        )
    if not content:
        raise BrowserlessTransientError(
            f"Browserless returned an empty body for {_redact_browserless_url(endpoint_url)}",
            cause="empty_body",
        )
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        raise BrowserlessTransientError(
            f"Browserless returned non-image content-type {content_type!r} for "
            f"{_redact_browserless_url(endpoint_url)}: {_sanitize_browserless_error(response.text[:200])}",
            cause="non_image",
        )
    if not content.startswith(b"\xff\xd8\xff"):  # JPEG start-of-image marker
        raise BrowserlessTransientError(
            f"Browserless returned a non-JPEG body for {_redact_browserless_url(endpoint_url)}",
            cause="non_jpeg",
        )
    return content


def _browserless_screenshot(endpoint_url: str, page_url: str, width: int, block_consent_modals: bool) -> bytes:
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
    if block_consent_modals:
        body["blockConsentModals"] = True
    if settings.HEATMAP_BROWSERLESS_BLOCK_ADS:
        body["blockAds"] = True

    timeout = (
        settings.HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS / 1000,
        settings.HEATMAP_BROWSERLESS_TIMEOUT_MS / 1000 + 30,
    )
    width_bucket = _width_bucket(width)
    started = time.monotonic()
    try:
        response = requests.post(endpoint_url, json=body, timeout=timeout)
    except Exception as e:
        elapsed = time.monotonic() - started
        HEATMAP_BROWSERLESS_REQUEST_SECONDS.labels(outcome="error", width_bucket=width_bucket).observe(elapsed)
        err: BrowserlessError = BrowserlessTransientError(
            f"Browserless screenshot request failed for {_redact_browserless_url(endpoint_url)}: "
            f"{_sanitize_browserless_error(str(e))}",
            cause="request_exception",
        )
        logger.warning(
            "heatmap_screenshot.browserless_request",
            width=width,
            outcome="error",
            cause="request_exception",
            latency_ms=round(elapsed * 1000),
        )
        raise err from None

    elapsed = time.monotonic() - started
    status_code = response.status_code
    byte_size = len(response.content or b"")

    if status_code != 200:
        HEATMAP_BROWSERLESS_REQUEST_SECONDS.labels(outcome="error", width_bucket=width_bucket).observe(elapsed)
        message = (
            f"Browserless screenshot failed ({status_code}) for "
            f"{_redact_browserless_url(endpoint_url)}: {_sanitize_browserless_error(response.text[:500])}"
        )
        error_cls = BrowserlessPermanentError if _is_permanent_status(status_code) else BrowserlessTransientError
        err = error_cls(message, status_code=status_code, cause="http_status")
        logger.warning(
            "heatmap_screenshot.browserless_request",
            width=width,
            browserless_status=status_code,
            latency_ms=round(elapsed * 1000),
            bytes=byte_size,
            outcome="error",
        )
        raise err

    try:
        content = _validate_screenshot_response(response, endpoint_url)
    except BrowserlessError as err:
        HEATMAP_BROWSERLESS_REQUEST_SECONDS.labels(outcome="error", width_bucket=width_bucket).observe(elapsed)
        logger.warning(
            "heatmap_screenshot.browserless_request",
            width=width,
            browserless_status=status_code,
            latency_ms=round(elapsed * 1000),
            bytes=byte_size,
            outcome="error",
            cause=err.cause,
        )
        raise

    HEATMAP_BROWSERLESS_REQUEST_SECONDS.labels(outcome="ok", width_bucket=width_bucket).observe(elapsed)
    logger.info(
        "heatmap_screenshot.browserless_request",
        width=width,
        browserless_status=status_code,
        latency_ms=round(elapsed * 1000),
        bytes=len(content),
        outcome="ok",
    )
    return content


def _resolve_widths(screenshot: SavedHeatmap) -> list[int]:
    target_widths = screenshot.target_widths or DEFAULT_TARGET_WIDTHS
    seen: set[int] = set()
    widths: list[int] = []
    for w in target_widths:
        if isinstance(w, int) and 100 <= w <= 3000 and w not in seen:
            widths.append(w)
            seen.add(w)
    if not widths:
        logger.warning(
            "heatmap_screenshot.no_valid_widths",
            screenshot_id=screenshot.id,
            team_id=screenshot.team_id,
            target_widths=target_widths,
        )
        return [1024]
    if len(widths) > MAX_TARGET_WIDTHS:
        logger.warning(
            "heatmap_screenshot.widths_capped",
            screenshot_id=screenshot.id,
            team_id=screenshot.team_id,
            requested_count=len(widths),
            cap=MAX_TARGET_WIDTHS,
        )
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
        raise BrowserlessPermanentError("Browserless screenshot URL is not configured", cause="not_configured")
    logger.info(
        "heatmap_screenshot.rendering_widths",
        screenshot_id=screenshot.id,
        team_id=screenshot.team_id,
        width_count=len(widths),
        widths=widths,
    )
    count = 0
    for w in widths:
        image_data = _browserless_screenshot(endpoint_url, screenshot.url, w, screenshot.block_consent_modals)
        _persist_snapshot(screenshot, w, image_data)
        count += 1
    return count


@shared_task(ignore_result=True, queue=CeleryQueue.EXPORTS.value)
@skip_team_scope_audit
def report_stuck_heatmap_screenshots() -> int:
    now = timezone.now()
    cutoff = now - timedelta(seconds=HEATMAP_SCREENSHOT_STUCK_THRESHOLD_SECONDS)
    stuck = SavedHeatmap.objects.filter(
        type=SavedHeatmap.Type.SCREENSHOT,
        status=SavedHeatmap.Status.PROCESSING,
        updated_at__lt=cutoff,
    )
    count = stuck.count()
    HEATMAP_SCREENSHOT_STUCK_PROCESSING.set(count)
    if count:
        sample = stuck.order_by("updated_at").only("id", "team_id", "updated_at")[:HEATMAP_SCREENSHOT_STUCK_SAMPLE_SIZE]
        logger.warning(
            "heatmap_screenshot.stuck_processing",
            stuck_count=count,
            threshold_seconds=HEATMAP_SCREENSHOT_STUCK_THRESHOLD_SECONDS,
            sample=[
                {
                    "screenshot_id": str(s.id),
                    "team_id": s.team_id,
                    "age_seconds": round((now - s.updated_at).total_seconds()),
                }
                for s in sample
            ],
        )
    return count
