from celery import Celery
from celery.schedules import crontab

from posthog.tasks.scheduled import add_periodic_task_with_expiry

from products.meep.backend.tasks import schedule_delegated_task_recovery


def register_periodic_tasks(sender: Celery) -> None:
    add_periodic_task_with_expiry(
        sender, crontab(minute="*"), schedule_delegated_task_recovery.s(), name="recover-meep-delegated-tasks"
    )
