from celery import shared_task
from structlog import get_logger

from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.ses_events_dlq import (
    ReplayOptions,
    ReplayReport,
    find_queue,
    replay_queue,
    sqs_client,
)
from products.workflows.backend.services.ses_events_dlq_runs import QueueLockLost, finish_run, hold_lock, update_run

logger = get_logger(__name__)


# No autoretry: a retry would post the messages the first attempt already left in the queue, and the
# person who started the run decides whether to start another one.
@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
def replay_ses_events_dlq_task(
    run_id: str, queue_name: str, dry_run: bool, limit: int, max_per_second: float, triggered_by: str
) -> None:
    queue = find_queue(queue_name)
    if queue is None:
        logger.warning("ses_events_dlq.unknown_queue", run_id=run_id, queue=queue_name)
        return
    options = ReplayOptions(dry_run=dry_run, limit=limit, max_per_second=max_per_second)
    if not hold_lock(run_id, queue, options):
        finish_run(run_id, queue, status="failed", error="Another run took this queue before this one started")
        return
    update_run(run_id, status="running")

    def on_progress(report: ReplayReport) -> None:
        update_run(run_id, status="running", report=report)
        if not hold_lock(run_id, queue, options):
            raise QueueLockLost("Another run took this queue")

    try:
        replay_queue(queue, options, sqs=sqs_client(queue), triggered_by=triggered_by, on_progress=on_progress)
    except Exception as error:
        logger.exception("ses_events_dlq.replay_failed", run_id=run_id, queue=queue_name)
        finish_run(run_id, queue, status="failed", error=f"{type(error).__name__}: {error}")
        return
    finish_run(run_id, queue, status="finished")
