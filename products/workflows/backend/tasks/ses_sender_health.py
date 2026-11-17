from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.providers.ses import SESProvider
from products.workflows.backend.services.ses_sender_health import record_ses_sending_status


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def check_ses_sender_health() -> None:
    record_ses_sending_status(SESProvider().list_failed_domain_identities())
