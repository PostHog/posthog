from typing import Any

from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.inbound_email.domains import sweep_active_domains
from products.workflows.backend.services.inbound_email.intake import process_notification
from products.workflows.backend.services.inbound_email.retention import (
    delete_expired_received_emails,
    delete_received_emails_for_persons,
)


@shared_task(
    ignore_result=True,
    # Reading and parsing can take a while, and this keeps a burst of mail away from the default queue.
    queue=CeleryQueue.LONG_RUNNING.value,
    # Retried work lands on the same rows and keys, and the intake object stays until every team has its copy.
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=900,
    max_retries=8,
    retry_jitter=True,
    # A task that kills its worker isn't requeued, so one message can't take down worker after worker. Its object stays
    # in intake.
    acks_late=True,
    # Reaching this during a parse keeps the raw message and marks it unparsed, so it doesn't fail the delivery.
    soft_time_limit=240,
    time_limit=300,
)
@skip_team_scope_audit
def process_inbound_email_task(notification: dict[str, Any]) -> None:
    process_notification(notification)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def delete_expired_received_emails_task() -> None:
    delete_expired_received_emails()


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def sweep_inbound_email_domains_task() -> None:
    sweep_active_domains()


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=900,
    max_retries=8,
    retry_jitter=True,
)
@skip_team_scope_audit
def delete_received_emails_for_persons_task(team_id: int, person_ids: list[str], addresses: list[str]) -> None:
    delete_received_emails_for_persons(team_id, person_ids, addresses)
