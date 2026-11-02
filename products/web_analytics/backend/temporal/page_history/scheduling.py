from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db.models import Count, F, Max, Min, OuterRef, Q, Subquery
from django.utils import timezone

from prometheus_client import Counter, Gauge

from posthog.models import Team

from products.web_analytics.backend.heatmap_history import (
    HEATMAP_HISTORY_GLOBAL_DAILY_CAP,
    HEATMAP_HISTORY_TICK_CAP,
    HeatmapHistoryService,
    capture_day,
    history_due_at,
    history_enabled,
    scheduled_requests_today,
)
from products.web_analytics.backend.heatmap_history_storage import delete_images_now
from products.web_analytics.backend.models import HeatmapCaptureRequest, HeatmapScreenshotHistory, SavedHeatmap
from products.web_analytics.backend.temporal.page_history.types import DueCapture

HEATMAP_HISTORY_VIEWED_WITHIN = timedelta(days=30)
HEATMAP_HISTORY_METADATA_BATCH = 2000
HEATMAP_HISTORY_DISPATCH_GRACE = timedelta(minutes=2)
HISTORY_SCHEDULED = Counter("heatmap_screenshot_history_scheduled", "Scheduled history captures")
HISTORY_PENDING = Gauge("heatmap_screenshot_history_pending", "Outstanding capture requests")
HISTORY_PENDING_AGE = Gauge(
    "heatmap_screenshot_history_pending_age_seconds", "Age of oldest outstanding capture request"
)
HISTORY_CLEANUP_BACKLOG = Gauge("heatmap_screenshot_history_cleanup_backlog", "Expired history rows awaiting cleanup")
HISTORY_EXPIRED = Counter("heatmap_screenshot_history_expired", "Expired history metadata")


def due_capture(request: HeatmapCaptureRequest, now: datetime) -> DueCapture:
    return DueCapture(
        team_id=request.team_id,
        request_id=str(request.id),
        seconds_left=(request.deadline - now).total_seconds(),
    )


def undispatched_captures(now: datetime) -> list[DueCapture]:
    stale = (
        HeatmapCaptureRequest.objects.unscoped()
        .filter(
            state=HeatmapCaptureRequest.State.QUEUED,
            created_at__lte=now - HEATMAP_HISTORY_DISPATCH_GRACE,
            deadline__gt=now + HEATMAP_HISTORY_DISPATCH_GRACE,
        )
        .order_by("created_at", "id")[:HEATMAP_HISTORY_TICK_CAP]
    )
    return [due_capture(request, now) for request in stale]


def schedule_due_captures() -> list[DueCapture]:
    if not settings.OBJECT_STORAGE_ENABLED:
        return []
    now = timezone.now()
    if scheduled_requests_today(now) >= HEATMAP_HISTORY_GLOBAL_DAILY_CAP:
        return undispatched_captures(now)
    eligible = SavedHeatmap.objects.filter(
        type=SavedHeatmap.Type.SCREENSHOT,
        source=SavedHeatmap.Source.SERVER,
        status=SavedHeatmap.Status.COMPLETED,
        deleted=False,
        is_prewarm=False,
        last_viewed_at__gte=now - HEATMAP_HISTORY_VIEWED_WITHIN,
    ).filter(Q(next_history_capture_at__lte=now) | Q(next_history_capture_at__isnull=True))
    last_dispatch = (
        HeatmapCaptureRequest.objects.unscoped()
        .filter(team_id=OuterRef("pk"), trigger=HeatmapScreenshotHistory.Trigger.SCHEDULED)
        .order_by()
        .values("team_id")
        .annotate(latest=Max("created_at"))
        .values("latest")
    )
    teams = (
        Team.objects.filter(id__in=eligible.values("team_id"))
        .annotate(last_dispatch=Subquery(last_dispatch))
        .order_by(F("last_dispatch").asc(nulls_first=True), "id")
        .only("id", "uuid", "organization_id", "timezone")
    )
    scheduled: list[DueCapture] = []
    candidates: dict[int, list[UUID]] = {}
    for team in teams:
        if not history_enabled(team):
            continue
        day = capture_day(now, team.timezone)
        due: list[UUID] = []
        backfill: list[SavedHeatmap] = []
        for heatmap_id, next_capture_at in (
            eligible.filter(team_id=team.id)
            .order_by("-last_viewed_at", "id")
            .values_list("id", "next_history_capture_at")
        ):
            due_at = next_capture_at or history_due_at(heatmap_id, day)
            if next_capture_at is None:
                backfill.append(SavedHeatmap(id=heatmap_id, team_id=team.id, next_history_capture_at=due_at))
            if due_at <= now:
                due.append(heatmap_id)
            if len(due) >= HEATMAP_HISTORY_TICK_CAP:
                break
        SavedHeatmap.objects.bulk_update(backfill, ["next_history_capture_at"])
        if due:
            candidates[team.id] = due
    while candidates and len(scheduled) < HEATMAP_HISTORY_TICK_CAP:
        for team_id in list(candidates):
            heatmap_id = candidates[team_id].pop(0)
            request = HeatmapHistoryService.enqueue(
                team_id=team_id,
                heatmap_id=heatmap_id,
                trigger=HeatmapScreenshotHistory.Trigger.SCHEDULED,
                dispatch=False,
            )
            if request is not None:
                scheduled.append(due_capture(request, now))
            if not candidates[team_id]:
                del candidates[team_id]
            if len(scheduled) >= HEATMAP_HISTORY_TICK_CAP:
                break
    HISTORY_SCHEDULED.inc(len(scheduled))
    return scheduled + undispatched_captures(now)


def prune_history() -> int:
    now = timezone.now()
    stale = (
        HeatmapCaptureRequest.objects.unscoped()
        .filter(state__in=HeatmapCaptureRequest.LIVE_STATES, deadline__lte=now)
        .order_by("deadline", "id")[:HEATMAP_HISTORY_METADATA_BATCH]
    )
    for request in stale:
        HeatmapHistoryService.fail(request, "worker_timeout")
    expired = list(
        HeatmapScreenshotHistory.objects.unscoped()
        .filter(expires_at__lte=now)
        .order_by("expires_at", "id")
        .values_list("id", flat=True)[:HEATMAP_HISTORY_METADATA_BATCH]
    )
    requests = list(
        HeatmapCaptureRequest.objects.unscoped()
        .filter(Q(expires_at__lte=now) | Q(history_id__in=expired))
        .order_by("expires_at", "id")
        .values_list("team_id", "id")[:HEATMAP_HISTORY_METADATA_BATCH]
    )
    by_team: dict[int, list[UUID]] = {}
    for team_id, request_id in requests:
        by_team.setdefault(team_id, []).append(request_id)
    undeletable = {request_id for team_id, ids in by_team.items() for request_id in delete_images_now(team_id, ids)}
    deleted, _ = (
        HeatmapCaptureRequest.objects.unscoped()
        .filter(id__in=[request_id for _, request_id in requests if request_id not in undeletable])
        .delete()
    )
    remaining = HEATMAP_HISTORY_METADATA_BATCH - len(requests)
    histories = list(
        HeatmapScreenshotHistory.objects.unscoped()
        .filter(id__in=expired, requests__isnull=True)
        .values_list("id", flat=True)[:remaining]
    )
    history_deleted, _ = HeatmapScreenshotHistory.objects.unscoped().filter(id__in=histories).delete()
    deleted += history_deleted
    HISTORY_EXPIRED.inc(len(histories))
    pending = (
        HeatmapCaptureRequest.objects.unscoped()
        .filter(state__in=HeatmapCaptureRequest.LIVE_STATES)
        .aggregate(oldest=Min("created_at"), count=Count("id"))
    )
    HISTORY_PENDING.set(pending["count"])
    HISTORY_PENDING_AGE.set((now - pending["oldest"]).total_seconds() if pending["oldest"] else 0)
    HISTORY_CLEANUP_BACKLOG.set(
        HeatmapScreenshotHistory.objects.unscoped().filter(expires_at__lte=now).count()
        + HeatmapCaptureRequest.objects.unscoped().filter(expires_at__lte=now).count()
    )
    return deleted
