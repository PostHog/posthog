from celery import shared_task
from celery.schedules import crontab

from ..facade import api

SESSION_BRIEFS_CRONTAB = crontab(minute="*/15")


@shared_task(ignore_result=True)
def post_session_briefs() -> None:
    api.post_due_briefs()
