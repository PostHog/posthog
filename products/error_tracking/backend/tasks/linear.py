from typing import Any, cast
from uuid import UUID

from django.db import DatabaseError

import requests
from celery import shared_task

from posthog.models.scoping import with_team_scope

from products.error_tracking.backend.facade import api, contracts


def enqueue_linear_external_references(event_type: str, payload: dict[str, Any]) -> None:
    for job in api.prepare_linear_external_reference_jobs(event_type, payload):
        cast(Any, process_linear_external_reference).delay(
            team_id=job.team_id,
            organization_id=job.organization_id,
            identifier=job.identifier,
            title=job.title,
            issue_id=str(job.issue_id) if job.issue_id is not None else None,
            fingerprint=job.fingerprint,
        )


@shared_task(
    name="products.error_tracking.backend.tasks.process_linear_external_reference",
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(DatabaseError, requests.RequestException),
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
@with_team_scope()
def process_linear_external_reference(
    *,
    team_id: int,
    organization_id: str,
    identifier: str,
    title: str,
    issue_id: str | None,
    fingerprint: str | None,
) -> None:
    api.link_linear_external_reference(
        contracts.LinearExternalReferenceJob(
            team_id=team_id,
            organization_id=organization_id,
            identifier=identifier,
            title=title,
            issue_id=UUID(issue_id) if issue_id is not None else None,
            fingerprint=fingerprint,
        )
    )
