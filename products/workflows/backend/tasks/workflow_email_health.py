from celery import shared_task
from structlog import get_logger

from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.workflow_email_health import sweep_workflow_email_health

logger = get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
def sweep_workflow_email_deliverability() -> None:
    """Pause the email of any workflow whose spam complaint or hard bounce rate breaches a
    threshold. Off by default: see WORKFLOW_EMAIL_AUTO_PAUSE_ENABLED."""
    applied = sweep_workflow_email_health()
    if applied:
        logger.warning("workflow_email_auto_pause_sweep_applied", paused=len(applied))
