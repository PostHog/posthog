from celery import shared_task
from structlog import get_logger

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.facade.contracts import EmailProviderUnavailableError
from products.workflows.backend.services.email_domain_verification import revoke_lost_email_domain_verifications

logger = get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def recheck_email_domain_verifications() -> None:
    try:
        revoked = revoke_lost_email_domain_verifications()
    except EmailProviderUnavailableError:
        # Nothing changed, and the next run reads SES again.
        logger.warning("Could not recheck email domain verifications", exc_info=True)
        return
    logger.info("Email domain verification recheck finished", revoked_senders=revoked)
