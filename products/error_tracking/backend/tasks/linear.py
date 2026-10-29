import random
from typing import Any, cast

from django.db import DatabaseError

import requests
from celery import Task, shared_task
from redis.exceptions import LockError

from posthog.models.integration import LinearIntegrationError, LinearRateLimitedError

from products.error_tracking.backend.facade import contracts

# Linear resets its rate limit at most an hour away, and the retry waits for the reset, so a few
# retries cover a token that stays throttled for several windows.
_RATE_LIMITED_MAX_RETRIES = 8
# Another job holds the issue for a few Linear reads. Waiting a short, spread-out time lets it finish.
_ISSUE_BUSY_MAX_RETRIES = 20
_ISSUE_BUSY_RETRY_SECONDS = (5, 30)


def enqueue_linear_status_sync(payload: dict[str, Any]) -> None:
    from products.error_tracking.backend.facade import (  # noqa: PLC0415 - the write facade imports lifecycle_events, which imports temporal, which imports this package
        issues,
    )

    job = issues.prepare_linear_status_sync_job(payload)
    if job is None:
        return
    cast(Any, process_linear_status_sync).delay(
        organization_id=job.organization_id,
        identifiers=list(job.identifiers),
        previous_state_id=job.previous_state_id,
    )


@shared_task(
    bind=True,
    name="products.error_tracking.backend.tasks.process_linear_status_sync",
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    # The sync decides from the states it reads from Linear, so a failed read must retry rather
    # than drop the delivery. Linear already holds the receipt and does not send it again.
    autoretry_for=(DatabaseError, LinearIntegrationError, requests.RequestException),
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def process_linear_status_sync(
    self: Task, *, organization_id: str, identifiers: list[str], previous_state_id: str
) -> None:
    from products.error_tracking.backend.facade import (  # noqa: PLC0415 - the write facade imports lifecycle_events, which imports temporal, which imports this package
        issues,
    )

    job = contracts.LinearStatusSyncJob(
        organization_id=organization_id,
        identifiers=tuple(identifiers),
        previous_state_id=previous_state_id,
    )
    try:
        issues.sync_linear_status(job)
    except LinearRateLimitedError as error:
        raise self.retry(exc=error, countdown=error.retry_after_seconds, max_retries=_RATE_LIMITED_MAX_RETRIES)
    except LockError as error:
        raise self.retry(
            exc=error, countdown=random.randint(*_ISSUE_BUSY_RETRY_SECONDS), max_retries=_ISSUE_BUSY_MAX_RETRIES
        )
