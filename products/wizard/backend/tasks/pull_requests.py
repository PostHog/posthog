from typing import Any

from django.db import DatabaseError

import structlog
from celery import shared_task
from celery.app.task import Task

from posthog.celery_queues import CeleryQueue

from products.wizard.backend.logic.artifacts import pull_requests
from products.wizard.backend.tasks.config import PROCESS_PULL_REQUEST_EVENT_TASK

logger = structlog.get_logger(__name__)

MAX_PULL_REQUEST_EVENT_RETRIES = 8


# GitHub does not redeliver once the consumer has enqueued this task, so the task retries on its own.
@shared_task(
    bind=True,
    ignore_result=True,
    name=PROCESS_PULL_REQUEST_EVENT_TASK,
    queue=CeleryQueue.DEFAULT.value,
    max_retries=MAX_PULL_REQUEST_EVENT_RETRIES,
)
def process_wizard_pull_request_event(self: Task, payload: dict[str, Any]) -> None:
    try:
        pull_requests.handle_pull_request_event(payload)
    except pull_requests.PullRequestArtifactNotStoredError as error:
        # A look-alike branch from outside the Wizard never gets an artifact, so give up quietly.
        if self.request.retries >= MAX_PULL_REQUEST_EVENT_RETRIES:
            logger.info("wizard_pull_request_event_without_artifact", pr_url=str(error))
            return
        raise self.retry(exc=error, countdown=_countdown(self.request.retries))
    except DatabaseError as error:
        raise self.retry(exc=error, countdown=_countdown(self.request.retries))


def _countdown(retries: int) -> int:
    return min(15 * 2**retries, 600)
