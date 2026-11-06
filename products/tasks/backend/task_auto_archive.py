from datetime import datetime, timedelta
from uuid import UUID

from django.db import OperationalError, ProgrammingError
from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone as django_timezone

import structlog
import psycopg.errors
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from posthog.exceptions_capture import capture_exception
from posthog.scoping_audit import skip_team_scope_audit

from products.tasks.backend.models import Channel, Task, TaskPin, TaskPresence, TaskRun

logger = structlog.get_logger(__name__)

AUTO_ARCHIVE_SWEEP_LIMIT = 5_000
_NON_TERMINAL_RUN_STATUSES = (
    TaskRun.Status.NOT_STARTED,
    TaskRun.Status.QUEUED,
    TaskRun.Status.IN_PROGRESS,
)


def _archivable_tasks(*, channel_id: UUID, team_id: int, cutoff: datetime, now: datetime) -> QuerySet[Task]:
    active_run = TaskRun.objects.filter(  # nosemgrep: celery-task-team-scope-audit
        task_id=OuterRef("pk"), team_id=team_id, status__in=_NON_TERMINAL_RUN_STATUSES
    )
    pin = TaskPin.objects.filter(
        task_id=OuterRef("pk"),
        task__team_id=team_id,
    )
    active_presence = TaskPresence.objects.for_team(team_id).filter(task_id=OuterRef("pk"), expires_at__gt=now)
    return (
        Task.objects.filter(  # nosemgrep: celery-task-team-scope-audit
            channel_id=channel_id,
            team_id=team_id,
            archived=False,
            deleted=False,
            internal=False,
            last_activity_at__lt=cutoff,
        )
        .filter(~Exists(active_run))
        .filter(~Exists(pin))
        .filter(~Exists(active_presence))
    )


def sweep_inactive_tasks(*, at: datetime | None = None, limit: int = AUTO_ARCHIVE_SWEEP_LIMIT) -> int:
    now = at or django_timezone.now()
    archived_count = 0
    policies = (
        Channel.objects.unscoped()
        .filter(deleted=False, auto_archive_after_days__isnull=False)
        .values_list("id", "team_id", "auto_archive_after_days")
        .iterator(chunk_size=500)
    )

    for channel_id, team_id, inactivity_days in policies:
        if inactivity_days is None:
            continue
        remaining = limit - archived_count
        if remaining <= 0:
            break
        cutoff = now - timedelta(days=inactivity_days)
        task_ids = list(
            _archivable_tasks(channel_id=channel_id, team_id=team_id, cutoff=cutoff, now=now)
            .order_by("last_activity_at")
            .values_list("id", flat=True)[:remaining]
        )
        if not task_ids:
            continue
        archived_count += (
            _archivable_tasks(channel_id=channel_id, team_id=team_id, cutoff=cutoff, now=now)
            .filter(id__in=task_ids)
            .update(archived=True, archived_at=now)
        )

    return archived_count


@shared_task(ignore_result=True, soft_time_limit=110, time_limit=170)
@skip_team_scope_audit
def sweep_inactive_tasks_task() -> None:
    try:
        archived_count = sweep_inactive_tasks()
    except SoftTimeLimitExceeded:
        raise
    except ProgrammingError as exc:
        if isinstance(exc.__cause__, psycopg.errors.UndefinedTable | psycopg.errors.UndefinedColumn):
            logger.debug("task_auto_archive.sweep_missing_schema", exception=exc)
            return
        capture_exception(exc)
        logger.exception("task_auto_archive.sweep_failed")
        return
    except OperationalError as exc:
        logger.warning("task_auto_archive.sweep_transient_db_error", error=str(exc))
        return
    except Exception as exc:
        capture_exception(exc)
        logger.exception("task_auto_archive.sweep_failed")
        return
    logger.info("task_auto_archive.swept", archived_count=archived_count)
