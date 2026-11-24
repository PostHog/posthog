"""Celery tasks for hogs."""

from celery import shared_task

from ..facade import api


@shared_task(ignore_result=True)
def fire_due_hog_schedules() -> None:
    api.fire_due_schedules()
