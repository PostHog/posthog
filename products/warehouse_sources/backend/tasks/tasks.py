import redis
import structlog
from celery import shared_task

from posthog.redis import get_client
from posthog.scoping_audit import skip_team_scope_audit

from products.warehouse_sources.backend.temporal.data_imports.reconcile_stuck_jobs import reconcile_stuck_running_jobs

logger = structlog.get_logger(__name__)

RECONCILE_STUCK_JOBS_LOCK = "warehouse_sources:reconcile_stuck_running_jobs"

# Generous bound on one sweep (bounded by STUCK_RUNNING_JOB_SWEEP_LIMIT describes plus queue
# consults); the lock auto-expires after this if a worker dies mid-sweep.
RECONCILE_STUCK_JOBS_LOCK_TIMEOUT_SECONDS = 5 * 60


@shared_task(
    ignore_result=True,
    name="products.warehouse_sources.backend.tasks.reconcile_stuck_running_data_import_jobs",
)
@skip_team_scope_audit
def reconcile_stuck_running_data_import_jobs() -> None:
    """Proactively fail v3 data import jobs wedged in RUNNING whose Temporal workflow is terminal.

    A non-blocking global lock keeps overlapping beat ticks from launching concurrent sweeps.
    """
    try:
        with get_client().lock(
            RECONCILE_STUCK_JOBS_LOCK,
            timeout=RECONCILE_STUCK_JOBS_LOCK_TIMEOUT_SECONDS,
            blocking=False,
        ):
            reconcile_stuck_running_jobs()
    except redis.exceptions.LockError:
        logger.info("reconcile_stuck_running_jobs_lock_contended")
