from celery import shared_task

from posthog.tasks.utils import CeleryQueue

from products.surveys.backend.desktop_feedback import sweep_expired_desktop_feedback_media


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sweep_expired_desktop_feedback_media_task() -> None:
    sweep_expired_desktop_feedback_media()
