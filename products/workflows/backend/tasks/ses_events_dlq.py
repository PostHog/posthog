from celery import shared_task
from structlog import get_logger

from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.ses_events_dlq import (
    MAX_HELD_MESSAGES,
    ReplayOptions,
    ReplayReport,
    StopReason,
    find_queue,
    replay_queue,
    sqs_client,
)
from products.workflows.backend.services.ses_events_dlq_runs import QueueLockLost, finish_run, hold_lock, update_run

logger = get_logger(__name__)

STOP_NOTES: dict[StopReason, str] = {
    "run_limit": "The run stopped after 11 hours. Start another run for the rest.",
    "held_limit": f"The run stopped after keeping {MAX_HELD_MESSAGES:,} events. Fix why they fail, then start another run.",
    "lease_lost": "The run stopped because SQS did not extend its hold on the kept events. Start another run.",
}


# No autoretry: a retry would post the messages the first attempt already left in the queue, and the
# person who started the run decides whether to start another one.
@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
def replay_ses_events_dlq_task(
    run_id: str, queue_name: str, dry_run: bool, limit: int, max_per_second: float, triggered_by: str
) -> None:
    queue = find_queue(queue_name)
    if queue is None:
        logger.warning("ses_events_dlq.unknown_queue", run_id=run_id, queue=queue_name)
        finish_run(run_id, queue_name, status="failed", error="This worker has no queue with this name")
        return
    options = ReplayOptions(dry_run=dry_run, limit=limit, max_per_second=max_per_second)
    if not hold_lock(run_id, queue):
        finish_run(
            run_id,
            queue_name,
            status="failed",
            error="This run could not take its queue. Another run held it, or this run waited too long to start.",
        )
        return
    update_run(run_id, status="running")

    def on_progress(report: ReplayReport) -> None:
        if not hold_lock(run_id, queue):
            raise QueueLockLost("Another run took this queue, or the page marked this run as stopped")
        update_run(run_id, status="running", report=report)

    try:
        report = replay_queue(queue, options, sqs=sqs_client(queue), triggered_by=triggered_by, on_progress=on_progress)
    except Exception as error:
        logger.exception("ses_events_dlq.replay_failed", run_id=run_id, queue=queue_name)
        finish_run(run_id, queue_name, status="failed", error=f"{type(error).__name__}: {error}")
        return
    notes = []
    if report.stopped_reason is not None:
        notes.append(STOP_NOTES[report.stopped_reason])
    if report.unreleased:
        logger.error("ses_events_dlq.messages_not_released", run_id=run_id, queue=queue_name, count=report.unreleased)
        notes.append(
            f"SQS did not release {report.unreleased} kept messages. "
            "They return to the queue when their visibility timeout ends."
        )
    finish_run(run_id, queue_name, status="finished", report=report, error=" ".join(notes) or None)
