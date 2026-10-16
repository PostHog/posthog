import structlog
from celery import shared_task

from posthog.redis import get_client, redis
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.batch_jobs import dispatch_batch_jobs_waiting_for_cohorts

logger = structlog.get_logger(__name__)

WAITING_BATCH_JOBS_SWEEP_LOCK = "workflows:waiting_batch_jobs_sweep"
# Expires a lock left by a killed worker. Set well above the time a pass should take.
WAITING_BATCH_JOBS_SWEEP_LOCK_TIMEOUT_SECONDS = 15 * 60


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def dispatch_batch_jobs_waiting_for_realtime_cohorts() -> None:
    # A pass over a large backlog can outlast the schedule interval, so a pass skips while another runs.
    try:
        with get_client().lock(
            WAITING_BATCH_JOBS_SWEEP_LOCK, timeout=WAITING_BATCH_JOBS_SWEEP_LOCK_TIMEOUT_SECONDS, blocking=False
        ):
            dispatch_batch_jobs_waiting_for_cohorts()
    except redis.exceptions.LockError:
        logger.info("waiting_batch_jobs_sweep_already_running")
