from typing import Any

from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.inbound_email.intake import process_notification
from products.workflows.backend.services.inbound_email.retention import delete_expired_received_emails


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    # Retried work lands on the same rows and keys, and the intake object stays until every team has its copy.
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=900,
    max_retries=8,
    retry_jitter=True,
    # SNS already has its receipt, so a killed worker must hand the message back rather than lose it.
    acks_late=True,
    reject_on_worker_lost=True,
    # The largest message SES accepts takes seconds to read and parse.
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
