from celery import current_app, signature

from .app_refresh import DISPATCH_TASK_NAME

current_app.add_periodic_task(
    60,
    signature(DISPATCH_TASK_NAME),
    name="dispatch notebook app refreshes",
    expires=90,
)
