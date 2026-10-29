from typing import Any, cast

from django.db import DatabaseError

import requests
from celery import shared_task

from posthog.models.integration import LinearIntegrationError

from products.error_tracking.backend.facade import contracts


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
def process_linear_status_sync(*, organization_id: str, identifiers: list[str], previous_state_id: str) -> None:
    from products.error_tracking.backend.facade import (  # noqa: PLC0415 - the write facade imports lifecycle_events, which imports temporal, which imports this package
        issues,
    )

    issues.sync_linear_status(
        contracts.LinearStatusSyncJob(
            organization_id=organization_id,
            identifiers=tuple(identifiers),
            previous_state_id=previous_state_id,
        )
    )
