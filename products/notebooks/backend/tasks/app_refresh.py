from datetime import timedelta
from functools import partial
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from celery import shared_task

from products.notebooks.backend.models import NotebookAppRefreshRun, NotebookAppSchedule

DISPATCH_TASK_NAME = "products.notebooks.backend.tasks.app_refresh.dispatch_notebook_app_refreshes"


@shared_task(ignore_result=True, soft_time_limit=720, time_limit=780)
def refresh_notebook_app(team_id: int, run_id: str) -> None:
    from products.notebooks.backend.app_refresh import run_slot

    run_slot(team_id, UUID(run_id))


@shared_task(name=DISPATCH_TASK_NAME, ignore_result=True, soft_time_limit=45, time_limit=55)
def dispatch_notebook_app_refreshes() -> None:
    from products.notebooks.backend.app_refresh import RUN_TIMEOUT, finish_run, notify_owner

    now = timezone.now()
    state = NotebookAppRefreshRun.Status
    expired = NotebookAppRefreshRun.objects.unscoped().filter(status=state.RUNNING, started_at__lt=now - RUN_TIMEOUT)
    for run in expired.order_by("started_at")[:64]:
        finish_run(run, None, "The refresh timed out.")
    with transaction.atomic():
        due = (
            NotebookAppSchedule.objects.unscoped()
            .select_for_update(skip_locked=True)
            .filter(enabled=True, next_due_at__lte=now)
            .defer("outputs")
            .order_by("next_due_at")
        )
        for schedule in due[:64]:
            runs = NotebookAppRefreshRun.objects.for_team(schedule.team_id).filter(schedule=schedule)
            if not runs.filter(status__in=[state.RUNNING, state.QUEUED]).exists():
                runs.get_or_create(
                    schedule=schedule,
                    due_at=schedule.next_due_at,
                    defaults={"revision": schedule.revision, "team_id": schedule.team_id},
                )
            schedule.next_due_at = now + timedelta(minutes=schedule.interval_minutes)
            schedule.save(update_fields=["next_due_at"])
    with transaction.atomic():
        stale = (
            NotebookAppSchedule.objects.unscoped()
            .select_for_update(skip_locked=True)
            .filter(enabled=True, stale_notified=False, stale_at__lte=now)
            .defer("outputs")
            .order_by("stale_at")
        )
        for schedule in stale[:64]:
            assert schedule.stale_at is not None
            schedule.stale_notified = True
            schedule.save(update_fields=["stale_notified"])
            transaction.on_commit(
                partial(
                    notify_owner,
                    schedule,
                    "Notebook app results are stale",
                    f"notebook:stale:{schedule.pk}:{schedule.stale_at.isoformat()}",
                )
            )
    # Redispatch a queued slot if a previous sweep exited before Celery accepted it.
    queued = NotebookAppRefreshRun.objects.unscoped().filter(status=state.QUEUED).order_by("due_at")
    for team_id, run_id in queued.values_list("team_id", "pk")[:64]:
        refresh_notebook_app.delay(team_id, str(run_id))
