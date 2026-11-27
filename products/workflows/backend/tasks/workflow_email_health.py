from django.core.cache import cache
from django.utils import timezone

from celery import shared_task
from structlog import get_logger

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.first_real_sends import capture_first_real_sends
from products.workflows.backend.services.workflow_email_health import sweep_workflow_email_health

logger = get_logger(__name__)

FIRST_REAL_SENDS_LOCK_KEY = "workflows_first_real_sends_running"
FIRST_REAL_SENDS_LOCK_TIMEOUT_SECONDS = 6 * 60 * 60


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
def sweep_workflow_email_deliverability() -> None:
    """Pause the email of any workflow whose spam complaint or hard bounce rate breaches a
    threshold. Off by default: see WORKFLOW_EMAIL_AUTO_PAUSE_ENFORCE."""
    applied = sweep_workflow_email_health()
    if applied:
        logger.warning("workflow_email_auto_pause_sweep_applied", paused=len(applied))


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def capture_workflow_first_real_sends() -> None:
    if not cache.add(FIRST_REAL_SENDS_LOCK_KEY, "running", timeout=FIRST_REAL_SENDS_LOCK_TIMEOUT_SECONDS):
        logger.info("workflows_first_real_sends_already_running")
        return
    try:
        capture_first_real_sends(now=timezone.now())
    finally:
        cache.delete(FIRST_REAL_SENDS_LOCK_KEY)
