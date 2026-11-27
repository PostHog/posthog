from celery import current_app
from celery.schedules import crontab

from .app_embeds import cleanup_expired_app_embeds

current_app.add_periodic_task(
    crontab(minute="7,22,37,52"),
    cleanup_expired_app_embeds.s(),
    name="remove expired notebook app embeds",
    expires=900,
)
