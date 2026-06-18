from datetime import datetime

from django.db import OperationalError, transaction
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)
from products.reminders.backend.constants import RESOURCE_MODELS
from products.reminders.backend.models import Reminder
from products.reminders.backend.scheduling import compute_next_fire_at, resolve_timezone

logger = structlog.get_logger(__name__)

MAX_RETRY_ATTEMPTS = 5
MAX_CATCHUP_ITERATIONS = 1000


def _build_source_url(reminder: Reminder) -> str:
    if reminder.team is None or not (reminder.resource_type and reminder.resource_id):
        return ""
    mapping = RESOURCE_MODELS.get(reminder.resource_type)
    if not mapping:
        return ""
    _, _, segment = mapping
    return f"/project/{reminder.team.project_id}/{segment}/{reminder.resource_id}"


def _fire(reminder: Reminder) -> None:
    if reminder.team_id is not None:
        data = NotificationData(
            team_id=reminder.team_id,
            notification_type=NotificationType.REMINDER,
            priority=Priority.CRITICAL,
            title=reminder.title,
            body=reminder.message,
            target_type=TargetType.USER,
            target_id=str(reminder.created_by_id),
            source_url=_build_source_url(reminder),
        )
    else:
        data = NotificationData(
            organization_id=reminder.organization_id,
            notification_type=NotificationType.REMINDER,
            priority=Priority.CRITICAL,
            title=reminder.title,
            body=reminder.message,
            target_type=TargetType.USER,
            target_id=str(reminder.created_by_id),
            source_url="",
        )
    create_notification(data)


def _advance(reminder: Reminder, now: datetime) -> None:
    if not (reminder.recurrence_interval or reminder.cron_expression):
        reminder.status = Reminder.Status.COMPLETED
        return
    tz = resolve_timezone(reminder.timezone)
    assert reminder.next_fire_at is not None  # due rows are filtered on next_fire_at__lte
    next_fire = compute_next_fire_at(
        reminder.next_fire_at,
        interval=reminder.recurrence_interval,
        cron_expression=reminder.cron_expression,
        tz=tz,
    )
    iterations = 0
    while next_fire <= now and iterations < MAX_CATCHUP_ITERATIONS:
        next_fire = compute_next_fire_at(
            next_fire, interval=reminder.recurrence_interval, cron_expression=reminder.cron_expression, tz=tz
        )
        iterations += 1
    if reminder.end_date and next_fire > reminder.end_date:
        reminder.status = Reminder.Status.COMPLETED
    else:
        reminder.next_fire_at = next_fire


def process_due_reminders() -> None:
    try:
        with transaction.atomic():
            due = (
                Reminder.objects.filter(status=Reminder.Status.ACTIVE, deleted=False, next_fire_at__lte=timezone.now())
                .select_related("team", "organization", "created_by")
                .select_for_update(nowait=True, of=("self",))
                .order_by("next_fire_at")[:10000]
            )
            for reminder in due:
                now = timezone.now()
                if reminder.created_by_id is None:
                    reminder.status = Reminder.Status.COMPLETED
                    reminder.last_error = "Reminder has no owner (creator was deleted)."
                    reminder.save(update_fields=["status", "last_error", "updated_at"])
                    continue
                if (
                    reminder.end_date
                    and reminder.end_date <= now
                    and (reminder.recurrence_interval or reminder.cron_expression)
                ):
                    reminder.status = Reminder.Status.COMPLETED
                    reminder.save(update_fields=["status", "updated_at"])
                    continue
                try:
                    _fire(reminder)
                    reminder.last_fired_at = now
                    reminder.failure_count = 0
                    reminder.last_error = None
                    _advance(reminder, now)
                    reminder.save()
                except Exception as e:
                    reminder.failure_count += 1
                    reminder.last_error = str(e)
                    if reminder.failure_count >= MAX_RETRY_ATTEMPTS:
                        if reminder.recurrence_interval or reminder.cron_expression:
                            _advance(reminder, now)
                            # Give the next window a fresh retry budget, like a successful fire does.
                            reminder.failure_count = 0
                            reminder.last_error = None
                        else:
                            reminder.status = Reminder.Status.ERRORED
                    reminder.save()
                    capture_exception(e)
    except OperationalError:
        pass
