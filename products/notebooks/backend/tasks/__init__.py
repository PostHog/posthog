from celery import current_app

from .app_embeds import cleanup_expired_app_embeds

current_app.add_periodic_task(
    900,
    cleanup_expired_app_embeds.s(),
    name="remove expired notebook app embeds",
    expires=900,
)
