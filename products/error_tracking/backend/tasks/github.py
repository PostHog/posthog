from typing import Any, Literal, cast
from uuid import UUID

from django.db import DatabaseError

from celery import shared_task

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.integration import GitHubIntegrationError
from posthog.models.scoping import with_team_scope

from products.error_tracking.backend.facade import api, contracts


def enqueue_github_external_references(event_type: str, payload: dict[str, Any]) -> None:
    for job in api.prepare_github_external_reference_jobs(event_type, payload):
        cast(Any, process_github_external_reference).delay(
            team_id=job.team_id,
            installation_id=job.installation_id,
            repository_full_name=job.repository_full_name,
            number=job.number,
            title=job.title,
            resource_type=job.resource_type,
            actor_login=job.actor_login,
            issue_id=str(job.issue_id) if job.issue_id is not None else None,
            fingerprint=job.fingerprint,
        )


@shared_task(
    name="products.error_tracking.backend.tasks.process_github_external_reference",
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    # The repo-permission lookup fails closed, so a transient GitHub error must retry rather than
    # drop the delivery, because a blip would otherwise lose a legitimate link for good.
    autoretry_for=(DatabaseError, GitHubIntegrationError, GitHubRateLimitError),
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
@with_team_scope()
def process_github_external_reference(
    *,
    team_id: int,
    installation_id: str,
    repository_full_name: str,
    number: int,
    title: str,
    resource_type: Literal["issue", "pull_request"],
    actor_login: str,
    issue_id: str | None,
    fingerprint: str | None,
) -> None:
    api.link_github_external_reference(
        contracts.GitHubExternalReferenceJob(
            team_id=team_id,
            installation_id=installation_id,
            repository_full_name=repository_full_name,
            number=number,
            title=title,
            resource_type=resource_type,
            actor_login=actor_login,
            issue_id=UUID(issue_id) if issue_id is not None else None,
            fingerprint=fingerprint,
        )
    )
