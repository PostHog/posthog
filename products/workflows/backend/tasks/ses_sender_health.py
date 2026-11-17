from botocore.exceptions import ClientError
from celery import shared_task
from structlog import get_logger

from posthog.exceptions_capture import capture_exception
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.providers.ses import SESProvider
from products.workflows.backend.services.ses_sender_health import record_ses_sending_status

logger = get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def check_ses_sender_health() -> None:
    try:
        failed_domains = SESProvider().list_failed_domain_identities()
    except Exception as error:
        error_code = error.response.get("Error", {}).get("Code") if isinstance(error, ClientError) else None
        logger.warning("SES sender health check could not list identities", error_code=error_code)
        capture_exception(error, {"error_code": error_code})
        raise
    record_ses_sending_status(failed_domains)
