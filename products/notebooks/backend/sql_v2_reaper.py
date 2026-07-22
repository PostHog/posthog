"""The kernel lane's watchdog: fail RUNNING node runs whose callback can never arrive.

The sandbox callback is best-effort (`runner._post_callback` swallows delivery failures),
so a dead kernel, an unreachable backend URL, or a torn-down sandbox leaves the run row
RUNNING forever — the frontend gives up polling and the run silently vanishes from every
metric (the survivorship bias sql_v2_observability.md gap 2 warns about). The direct lane
has its own poll-driven watchdog (`sync_direct_run`); this task is the equivalent backstop
for every lane, run periodically from Celery beat.
"""

from datetime import timedelta

from django.utils import timezone

import structlog

from posthog.ph_client import ph_scoped_capture

from products.notebooks.backend.models import NotebookNodeRun
from products.notebooks.backend.sql_v2_metrics import OUTCOME_TIMED_OUT, record_node_run_terminal

logger = structlog.get_logger(__name__)

# Past every legitimate in-flight window: dispatch retries (3 x 5 min start-to-close),
# the kernel's object-materialization poll deadline (11 min), and the cell execution
# budget (5 min). A run still RUNNING after this has lost its callback for good.
STALE_RUN_DEADLINE = timedelta(minutes=40)

STALE_RUN_ERROR = "The run timed out without reporting a result. Re-run the node."

# Bounds one beat tick's work; the next tick drains the rest. Far above any real backlog.
_REAP_BATCH_SIZE = 500


def mark_stale_node_runs_failed() -> int:
    """Fail every RUNNING run older than STALE_RUN_DEADLINE; return how many were reaped.

    Cross-team by design (`unscoped()`): the reaper sweeps the whole table. Each transition
    is a guarded UPDATE so a callback that lands mid-sweep wins the row instead of being
    overwritten, and each reaped run is recorded once with outcome `timed_out`.
    """
    cutoff = timezone.now() - STALE_RUN_DEADLINE
    stale_ids = list(
        NotebookNodeRun.objects.unscoped()
        .filter(status=NotebookNodeRun.Status.RUNNING, created_at__lt=cutoff)
        .order_by("created_at")
        .values_list("id", flat=True)[:_REAP_BATCH_SIZE]
    )
    if not stale_ids:
        return 0

    reaped = 0
    with ph_scoped_capture() as capture:
        for run_id in stale_ids:
            updated = (
                NotebookNodeRun.objects.unscoped()
                .filter(id=run_id, status=NotebookNodeRun.Status.RUNNING)
                .update(
                    status=NotebookNodeRun.Status.FAILED,
                    error=STALE_RUN_ERROR,
                    updated_at=timezone.now(),
                )
            )
            if not updated:
                continue
            run = NotebookNodeRun.objects.unscoped().select_related("user", "notebook").get(id=run_id)
            record_node_run_terminal(run, OUTCOME_TIMED_OUT, capture=capture)
            reaped += 1

    if reaped:
        logger.info("notebook_stale_node_runs_reaped", count=reaped)
    return reaped
