from celery import shared_task

from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.providers.ses import SESProvider


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    # The team's own list already dropped the address, so nothing else retries this cleanup. Without a
    # retry, SES throttling or an outage leaves the address blocked and the next refusal re-suppresses it.
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=5,
    retry_jitter=True,
)
def clear_ses_bounce_suppression_task(email: str) -> None:
    SESProvider().clear_bounce_suppression(email)
