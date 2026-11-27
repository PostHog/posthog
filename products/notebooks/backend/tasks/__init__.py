from celery import current_app
from celery.schedules import crontab

from posthog.tasks.scheduled import add_periodic_task_with_expiry

from .app_embeds import cleanup_expired_app_embeds

add_periodic_task_with_expiry(
    current_app,
    crontab(minute="7,22,37,52"),
    cleanup_expired_app_embeds.s(),
    name="remove expired notebook app embeds",
    expires_seconds=900,
)
