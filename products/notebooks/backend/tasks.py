from uuid import UUID

from celery import shared_task

from posthog.celery_queues import CeleryQueue

from products.notebooks.backend.widgets import run_widget_generation_job


@shared_task(
    ignore_result=True,
    name="products.notebooks.generate_widget",
    queue=CeleryQueue.LONG_RUNNING.value,
)
def generate_widget(job_id: str) -> None:
    run_widget_generation_job(UUID(job_id))
