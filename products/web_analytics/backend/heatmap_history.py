import json
import hashlib
from datetime import UTC, date, datetime, time, timedelta
from io import BytesIO
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync
from PIL import Image
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.models import Team
from posthog.scheduling.jitter import deterministic_offset
from posthog.security.url_validation import is_url_allowed
from posthog.storage.object_storage import ObjectStorageError
from posthog.temporal.common.client import async_connect

from products.web_analytics.backend.api.heatmaps_utils import capture_image_within_limits, heatmaps_flag_enabled
from products.web_analytics.backend.heatmap_history_expiry import cancel_live_requests
from products.web_analytics.backend.heatmap_history_storage import delete_images_on_commit, write_image
from products.web_analytics.backend.models import HeatmapCaptureRequest, HeatmapScreenshotHistory, SavedHeatmap
from products.web_analytics.backend.tasks.heatmap_screenshot import (
    BrowserlessPermanentError,
    PageHttpStatusError,
    _classify_failure,
    _resolve_widths,
    render_page,
)
from products.web_analytics.backend.temporal.page_history.types import (
    CAPTURE_WORKFLOW_NAME,
    RENDER_RETRY_DELAY,
    CaptureInputs,
    RenderOutcome,
    capture_workflow_id,
    tick_start,
)

logger = structlog.get_logger(__name__)
HEATMAPS_PAGE_HISTORY_FLAG = "heatmaps-page-history"
HEATMAP_HISTORY_PREFERRED_WIDTH = 1024
HEATMAP_HISTORY_RETENTION = timedelta(days=90)
HEATMAP_HISTORY_MANUAL_COOLDOWN = timedelta(minutes=10)
HEATMAP_HISTORY_REQUEST_TIMEOUT = timedelta(minutes=30)
HEATMAP_HISTORY_TEAM_DAILY_CAP = 100
HEATMAP_HISTORY_GLOBAL_DAILY_CAP = 5000
HEATMAP_HISTORY_TICK_CAP = 18
HISTORY_CAPTURES = Counter("heatmap_screenshot_history_captures", "History capture outcomes", ["outcome", "cause"])


class CaptureCooldown(ValueError):
    pass


class CaptureDispatchError(Exception):
    pass


@frozen
class CaptureDay:
    captured_on: date
    timezone: str
    start: datetime
    end: datetime


def capture_day(now: datetime, timezone_name: str) -> CaptureDay:
    zone = ZoneInfo(timezone_name)
    day = now.astimezone(zone).date()
    return CaptureDay(
        captured_on=day,
        timezone=timezone_name,
        start=datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC),
        end=datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC),
    )


def history_due_at(heatmap_id: UUID, day: CaptureDay) -> datetime:
    return day.start + deterministic_offset(str(heatmap_id), day.end - day.start - HEATMAP_HISTORY_REQUEST_TIMEOUT)


def next_history_due_at(heatmap_id: UUID, day: CaptureDay) -> datetime:
    return history_due_at(heatmap_id, capture_day(day.end + timedelta(seconds=1), day.timezone))


def advisory_xact_lock(key: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [key])


def history_width(heatmap: SavedHeatmap) -> int:
    widths = _resolve_widths(heatmap)
    return min(widths, key=lambda width: (abs(width - HEATMAP_HISTORY_PREFERRED_WIDTH), width))


def history_enabled(team: Team) -> bool:
    return heatmaps_flag_enabled(
        HEATMAPS_PAGE_HISTORY_FLAG, str(team.uuid), team_id=team.id, organization_id=str(team.organization_id)
    )


def capture_signature(heatmap: SavedHeatmap) -> str:
    inputs = [
        heatmap.url,
        heatmap.data_url,
        history_width(heatmap),
        heatmap.block_consent_modals,
        heatmap.type,
        heatmap.source,
        heatmap.team.timezone,
        str(heatmap.history_configuration_revision),
    ]
    return hashlib.sha256(json.dumps(inputs).encode()).hexdigest()


def history_eligible(heatmap: SavedHeatmap) -> bool:
    return (
        settings.OBJECT_STORAGE_ENABLED
        and not heatmap.deleted
        and not heatmap.is_prewarm
        and heatmap.type == SavedHeatmap.Type.SCREENSHOT
        and heatmap.source == SavedHeatmap.Source.SERVER
    )


def capture_still_wanted(heatmap: SavedHeatmap | None, request: HeatmapCaptureRequest, enabled: bool) -> bool:
    return (
        heatmap is not None
        and enabled
        and history_eligible(heatmap)
        and request.input_signature == capture_signature(heatmap)
        and timezone.now() < request.deadline
    )


def scheduled_requests_today(now: datetime) -> int:
    utc_start = datetime.combine(now.date(), time.min, tzinfo=UTC)
    return (
        HeatmapCaptureRequest.objects.unscoped()
        .filter(
            trigger=HeatmapScreenshotHistory.Trigger.SCHEDULED,
            created_at__gte=utc_start,
            created_at__lt=utc_start + timedelta(days=1),
        )
        .count()
    )


def defer_to_next_day(heatmap: SavedHeatmap, day: CaptureDay) -> None:
    SavedHeatmap.objects.filter(team_id=heatmap.team_id, id=heatmap.id).update(
        next_history_capture_at=next_history_due_at(heatmap.id, day)
    )


async def start_capture_workflow(request: HeatmapCaptureRequest) -> None:
    client = await async_connect()
    await client.start_workflow(
        CAPTURE_WORKFLOW_NAME,
        CaptureInputs(team_id=request.team_id, request_id=str(request.id)),
        id=capture_workflow_id(str(request.id)),
        task_queue=settings.WEB_ANALYTICS_TASK_QUEUE,
        execution_timeout=max(request.deadline - timezone.now(), timedelta(seconds=1)),
    )


class HeatmapHistoryService:
    @staticmethod
    def enqueue(*, team_id: int, heatmap_id: UUID, trigger: str, dispatch: bool = True) -> HeatmapCaptureRequest | None:
        candidate = SavedHeatmap.objects.select_related("team").get(team_id=team_id, id=heatmap_id)
        if not history_eligible(candidate) or not history_enabled(candidate.team):
            return None
        now = timezone.now()
        scheduled = trigger == HeatmapScreenshotHistory.Trigger.SCHEDULED
        with transaction.atomic():
            if scheduled:
                advisory_xact_lock(f"heatmap-history:{now.date()}")
            heatmap = (
                SavedHeatmap.objects.select_for_update(of=("self",))
                .select_related("team")
                .get(team_id=team_id, id=heatmap_id)
            )
            if not history_eligible(heatmap):
                return None
            day = capture_day(now, heatmap.team.timezone)
            requests = HeatmapCaptureRequest.objects.for_team(team_id).filter(heatmap=heatmap)
            if scheduled:
                advisory_xact_lock(f"heatmap-history-team:{team_id}:{day.captured_on}")
                global_count = scheduled_requests_today(now)
                team_count = (
                    HeatmapCaptureRequest.objects.for_team(team_id)
                    .filter(trigger=trigger, captured_on=day.captured_on)
                    .count()
                )
                tick_count = (
                    HeatmapCaptureRequest.objects.unscoped()
                    .filter(trigger=trigger, created_at__gte=tick_start(now))
                    .count()
                )
                if team_count >= HEATMAP_HISTORY_TEAM_DAILY_CAP:
                    defer_to_next_day(heatmap, day)
                    return None
                if global_count >= HEATMAP_HISTORY_GLOBAL_DAILY_CAP or tick_count >= HEATMAP_HISTORY_TICK_CAP:
                    return None
                already_requested = requests.filter(captured_on=day.captured_on, trigger=trigger).exists()
                already_captured = (
                    HeatmapScreenshotHistory.objects.for_team(team_id)
                    .filter(
                        heatmap=heatmap,
                        captured_on=day.captured_on,
                        status=HeatmapScreenshotHistory.Status.OK,
                        expires_at__gt=now,
                        revision__isnull=False,
                    )
                    .exists()
                )
                if already_requested or already_captured:
                    defer_to_next_day(heatmap, day)
                    return None
                if requests.filter(state__in=HeatmapCaptureRequest.LIVE_STATES).exists():
                    return None
            elif (
                requests.filter(trigger=trigger, created_at__gt=now - HEATMAP_HISTORY_MANUAL_COOLDOWN)
                .exclude(failure_cause="dispatch_failed")
                .exists()
            ):
                raise CaptureCooldown("A capture was requested in the last 10 minutes")
            width = history_width(heatmap)
            expires_at = now + HEATMAP_HISTORY_RETENTION
            history, _ = HeatmapScreenshotHistory.objects.for_team(team_id).get_or_create(
                heatmap=heatmap,
                captured_on=day.captured_on,
                defaults={
                    "team_id": team_id,
                    "width": width,
                    "timezone": day.timezone,
                    "day_start": day.start,
                    "day_end": day.end,
                    "expires_at": expires_at,
                    "status": HeatmapScreenshotHistory.Status.PENDING,
                },
            )
            cancel_live_requests(team_id=team_id, heatmap_id=heatmap.id)
            request = HeatmapCaptureRequest.objects.for_team(team_id).create(
                team_id=team_id,
                heatmap=heatmap,
                history=history,
                trigger=trigger,
                captured_on=day.captured_on,
                timezone=day.timezone,
                day_start=day.start,
                day_end=day.end,
                width=width,
                url=heatmap.url,
                block_consent_modals=heatmap.block_consent_modals,
                input_signature=capture_signature(heatmap),
                deadline=min(now + HEATMAP_HISTORY_REQUEST_TIMEOUT, day.end),
                expires_at=expires_at,
                created_at=now,
            )
            history.latest_request = request
            if not history.has_content:
                history.status = HeatmapScreenshotHistory.Status.PENDING
            history.save(update_fields=["latest_request", "status", "updated_at"])
            if scheduled:
                defer_to_next_day(heatmap, day)
            if dispatch:
                transaction.on_commit(lambda: HeatmapHistoryService.dispatch(request))
        return request

    @staticmethod
    def dispatch(request: HeatmapCaptureRequest) -> None:
        try:
            async_to_sync(start_capture_workflow)(request)
        except Exception as error:
            HeatmapHistoryService.fail(request, "dispatch_failed")
            raise CaptureDispatchError("Could not queue the capture") from error

    @staticmethod
    def fail(
        request: HeatmapCaptureRequest,
        cause: str,
        page_status: int | None = None,
        state: HeatmapCaptureRequest.State = HeatmapCaptureRequest.State.FAILED,
    ) -> None:
        updated = (
            HeatmapCaptureRequest.objects.for_team(request.team_id)
            .filter(id=request.id, state__in=HeatmapCaptureRequest.LIVE_STATES, claim_id=request.claim_id)
            .update(
                state=state,
                completed_at=timezone.now(),
                failure_cause=cause,
                page_status=page_status,
            )
        )
        if not updated:
            return
        HeatmapScreenshotHistory.objects.for_team(request.team_id).filter(
            id=request.history_id,
            latest_request_id=request.id,
            revision__isnull=True,
        ).update(status=HeatmapScreenshotHistory.Status.FAILED, failure_cause=cause, page_status=page_status)
        delete_images_on_commit(request.team_id, [request.id])
        HISTORY_CAPTURES.labels(outcome="failed", cause=cause).inc()

    @staticmethod
    def claim(*, team_id: int, request_id: UUID) -> HeatmapCaptureRequest | None:
        queued = (
            HeatmapCaptureRequest.objects.for_team(team_id)
            .filter(id=request_id)
            .select_related("heatmap__team")
            .first()
        )
        if queued is None:
            return None
        enabled = history_enabled(queued.heatmap.team)
        with transaction.atomic():
            heatmap = (
                SavedHeatmap.objects.select_for_update(of=("self",))
                .select_related("team")
                .filter(team_id=team_id, id=queued.heatmap_id)
                .first()
            )
            request = (
                HeatmapCaptureRequest.objects.for_team(team_id)
                .select_for_update()
                .filter(id=request_id, state=HeatmapCaptureRequest.State.QUEUED)
                .first()
            )
            if heatmap is None or request is None:
                return None
            current = (
                HeatmapScreenshotHistory.objects.for_team(team_id)
                .filter(id=request.history_id, latest_request_id=request.id)
                .exists()
            )
            if not current or not capture_still_wanted(heatmap, request, enabled):
                HeatmapHistoryService.fail(request, "capture_cancelled", state=HeatmapCaptureRequest.State.CANCELLED)
                return None
            request.state = HeatmapCaptureRequest.State.RUNNING
            request.claim_id = uuid4()
            request.save(update_fields=["state", "claim_id"])
            return request

    @staticmethod
    def render(request: HeatmapCaptureRequest) -> bytes:
        allowed, _ = is_url_allowed(request.url)
        if not allowed:
            raise BrowserlessPermanentError("Page URL cannot be rendered", cause="ssrf_blocked")
        image = render_page(
            request.team_id,
            request.url,
            request.width,
            request.block_consent_modals,
            priority=Priority.BATCH,
            source="heatmap_screenshot_history",
        )
        try:
            if not image.endswith(b"\xff\xd9"):
                raise ValueError("Screenshot is not a complete JPEG")
            with Image.open(BytesIO(image), formats=["JPEG"]) as screenshot:
                if screenshot.width != request.width or not capture_image_within_limits(
                    screenshot.width, screenshot.height
                ):
                    raise ValueError("Screenshot dimensions or size are invalid")
                screenshot.load()
        except Exception as error:
            raise BrowserlessPermanentError("Screenshot is not a valid JPEG", cause="invalid_image") from error
        return image

    @staticmethod
    def thumbnail(image: bytes) -> bytes | None:
        try:
            with Image.open(BytesIO(image), formats=["JPEG"]) as screenshot:
                screenshot.draft("RGB", (640, 640))
                preview = screenshot.crop(
                    (0, 0, screenshot.width, min(screenshot.height, int(screenshot.width * 0.75)))
                ).convert("RGB")
                preview.thumbnail((320, 320))
                buffer = BytesIO()
                preview.save(buffer, format="JPEG", quality=70, optimize=True)
                return buffer.getvalue()
        except Exception:
            logger.warning("heatmap_history.thumbnail_failed", exc_info=True)
            return None

    @staticmethod
    def publish(request: HeatmapCaptureRequest, thumbnail_available: bool) -> None:
        team = Team.objects.filter(id=request.team_id).first()
        enabled = team is not None and history_enabled(team)
        with transaction.atomic():
            heatmap = (
                SavedHeatmap.objects.select_for_update(of=("self",))
                .select_related("team")
                .filter(team_id=request.team_id, id=request.heatmap_id)
                .first()
            )
            current = (
                HeatmapCaptureRequest.objects.for_team(request.team_id)
                .select_for_update()
                .filter(id=request.id, state=HeatmapCaptureRequest.State.RUNNING, claim_id=request.claim_id)
                .first()
            )
            history = (
                HeatmapScreenshotHistory.objects.for_team(request.team_id)
                .select_for_update()
                .filter(id=request.history_id, latest_request_id=request.id)
                .first()
            )
            if current is None:
                delete_images_on_commit(request.team_id, [request.id])
                return
            if history is None or not capture_still_wanted(heatmap, request, enabled):
                HeatmapHistoryService.fail(request, "capture_cancelled", state=HeatmapCaptureRequest.State.CANCELLED)
                return
            retired = history.revision
            history.revision = request.id
            history.has_thumbnail = thumbnail_available
            history.captured_at = timezone.now()
            history.width = request.width
            history.timezone = request.timezone
            history.day_start = request.day_start
            history.day_end = request.day_end
            history.expires_at = request.expires_at
            history.status = HeatmapScreenshotHistory.Status.OK
            history.trigger = request.trigger
            history.failure_cause = None
            history.page_status = None
            history.save()
            current.state = HeatmapCaptureRequest.State.SUCCEEDED
            current.completed_at = timezone.now()
            current.save(update_fields=["state", "completed_at"])
            if retired is not None and retired != request.id:
                delete_images_on_commit(request.team_id, [retired])
        HISTORY_CAPTURES.labels(outcome="ok", cause="").inc()

    @staticmethod
    def load_claimed(*, team_id: int, request_id: UUID, claim_id: UUID) -> HeatmapCaptureRequest | None:
        return (
            HeatmapCaptureRequest.objects.for_team(team_id)
            .filter(id=request_id, state=HeatmapCaptureRequest.State.RUNNING, claim_id=claim_id)
            .first()
        )

    @staticmethod
    def render_and_store(request: HeatmapCaptureRequest, *, final_attempt: bool) -> RenderOutcome:
        try:
            image = HeatmapHistoryService.render(request)
            write_image(request.team_id, request.id, "full", image)
            thumbnail = HeatmapHistoryService.thumbnail(image)
            if thumbnail is not None:
                try:
                    write_image(request.team_id, request.id, "thumbnail", thumbnail)
                except Exception:
                    logger.warning("heatmap_history.thumbnail_write_failed", exc_info=True)
                    thumbnail = None
        except BrowserlessPermanentError as error:
            return RenderOutcome(
                failure_cause=_classify_failure(error),
                page_status=error.status_code if isinstance(error, PageHttpStatusError) else None,
            )
        except Exception as error:
            if not final_attempt and timezone.now() + RENDER_RETRY_DELAY < request.deadline:
                raise
            return RenderOutcome(
                failure_cause="storage_write_failed"
                if isinstance(error, ObjectStorageError)
                else _classify_failure(error)
            )
        return RenderOutcome(has_thumbnail=thumbnail is not None)
