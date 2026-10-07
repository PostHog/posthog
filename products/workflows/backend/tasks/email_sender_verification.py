from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.email_sender_verification import EmailSenderVerification


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def refresh_pending_email_senders() -> None:
    EmailSenderVerification.refresh_pending()
