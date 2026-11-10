from typing import Any

from django.db import DatabaseError

from celery import shared_task

from posthog.celery_queues import CeleryQueue

from products.wizard.backend.logic.artifacts import pull_requests
from products.wizard.backend.tasks.config import PROCESS_PULL_REQUEST_EVENT_TASK


# GitHub does not redeliver once the consumer has enqueued this task, so a database error retries here.
@shared_task(
    ignore_result=True,
    name=PROCESS_PULL_REQUEST_EVENT_TASK,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(DatabaseError,),
    retry_backoff=True,
    max_retries=5,
)
def process_wizard_pull_request_event(payload: dict[str, Any]) -> None:
    pull_requests.handle_pull_request_event(payload)
