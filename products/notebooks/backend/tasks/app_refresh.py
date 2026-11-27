from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import F, Q, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, limit_concurrency

from products.notebooks.backend.models import NotebookAppRefreshRun, NotebookAppSchedule

logger = structlog.get_logger(__name__)
DISPATCH_LEASE = timedelta(minutes=5)
DISPATCH_TASK_NAME = "products.notebooks.backend.tasks.app_refresh.dispatch_notebook_app_refreshes"


@shared_task(
    ignore_result=True,
    soft_time_limit=720,
    time_limit=780,
    queue=CeleryQueue.LONG_RUNNING.value,
    autoretry_for=(ConcurrencyLimitExceeded,),
    retry_backoff=True,
    max_retries=3,
)
@limit_concurrency(24, limit_name="scheduled_global")
@limit_concurrency(3, key=lambda team_id, run_id: team_id, limit_name="scheduled_team")
def refresh_notebook_app(team_id: int, run_id: str) -> None:
    from products.notebooks.backend.app_refresh import run_slot

    run_slot(team_id, UUID(run_id))


@shared_task(name=DISPATCH_TASK_NAME, ignore_result=True, soft_time_limit=45, time_limit=55)
def dispatch_notebook_app_refreshes() -> None:
    from products.notebooks.backend.app_refresh import RUN_TIMEOUT, deliver_failure, finish_run, notify_owner

    now = timezone.now()
    state = NotebookAppRefreshRun.Status
    expired = NotebookAppRefreshRun.objects.unscoped().filter(status=state.RUNNING, started_at__lt=now - RUN_TIMEOUT)
    for run in expired.order_by("started_at")[:64]:
        finish_run(run, None, "The refresh timed out.")
    with transaction.atomic():
        eligible = NotebookAppSchedule.objects.unscoped().filter(enabled=True, next_due_at__lte=now)
        per_team = eligible.annotate(
            team_rank=Window(RowNumber(), partition_by=[F("team_id")], order_by=[F("next_due_at").asc(), F("pk").asc()])
        ).filter(team_rank__lte=4)
        due = (
            eligible.select_for_update(skip_locked=True)
            .filter(pk__in=per_team.values("pk"))
            .defer("outputs")
            .order_by("next_due_at", "pk")
        )
        for schedule in due[:64]:
            runs = NotebookAppRefreshRun.objects.for_team(schedule.team_id).filter(schedule=schedule)
            if not runs.filter(status__in=[state.RUNNING, state.QUEUED]).exists():
                runs.get_or_create(
                    schedule=schedule,
                    due_at=schedule.next_due_at,
                    defaults={
                        "revision": schedule.revision,
                        "team_id": schedule.team_id,
                        "owner_id": schedule.owner_id,
                    },
                )
            schedule.next_due_at = now + timedelta(minutes=schedule.interval_minutes)
            schedule.save(update_fields=["next_due_at"])
    stale = (
        NotebookAppSchedule.objects.unscoped()
        .filter(enabled=True, stale_notified=False, stale_at__lte=now)
        .select_related("notebook")
        .defer("outputs")
        .order_by("stale_at")
    )
    for schedule in stale[:64]:
        assert schedule.stale_at is not None
        try:
            notify_owner(
                schedule,
                "Notebook app results are stale",
                f"notebook:stale:{schedule.pk}:{schedule.stale_at.isoformat()}",
            )
        except Exception:
            logger.exception("notebook_app_stale_notification_failed", schedule_id=str(schedule.pk))
        else:
            NotebookAppSchedule.objects.for_team(schedule.team_id).filter(
                pk=schedule.pk, owner_id=schedule.owner_id, stale_at=schedule.stale_at
            ).update(stale_notified=True)
    failures = NotebookAppRefreshRun.objects.unscoped().filter(failure_notification_pending=True).order_by("due_at")
    for team_id, run_id in failures.values_list("team_id", "pk")[:64]:
        deliver_failure(team_id, run_id)
    with transaction.atomic():
        queued = (
            NotebookAppRefreshRun.objects.unscoped()
            .select_for_update(skip_locked=True)
            .filter(Q(dispatched_at__isnull=True) | Q(dispatched_at__lt=now - DISPATCH_LEASE), status=state.QUEUED)
            .order_by("due_at")
        )
        claimed = list(queued.values_list("team_id", "pk")[:64])
        NotebookAppRefreshRun.objects.unscoped().filter(pk__in=[run_id for _, run_id in claimed]).update(
            dispatched_at=now
        )
    for team_id, run_id in claimed:
        refresh_notebook_app.delay(team_id, str(run_id))
