from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.email_sender_verification import (
    NEW_SENDERS,
    SETTLED_SENDERS,
    EmailSenderVerification,
)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value, time_limit=110)
@skip_team_scope_audit
def refresh_new_email_senders() -> None:
    EmailSenderVerification.refresh_pending(NEW_SENDERS)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value, time_limit=270)
@skip_team_scope_audit
def refresh_settled_email_senders() -> None:
    EmailSenderVerification.refresh_pending(SETTLED_SENDERS)
