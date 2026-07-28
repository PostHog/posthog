"""
Celery-task wiring for the tasks product.

Re-exports the beat-scheduled loop sweeps that core's scheduler registers.
"""

from celery import shared_task

from products.tasks.backend.loop_reconciliation import reconcile_loop_trigger_schedules_task
from products.tasks.backend.loop_retention import sweep_loop_task_retention_task

__all__ = ["reconcile_loop_trigger_schedules_task", "sweep_loop_task_retention_task"]


# Retry budget for the verification deadline: doubling from 60s, so the last attempt lands
# roughly 8 minutes out. Covers a Temporal blip long enough that the run does not sit
# non-terminal forever, without hammering a namespace that is genuinely down.
CANCEL_VERIFICATION_MAX_RETRIES = 3
CANCEL_VERIFICATION_RETRY_DELAY_SECONDS = 60


@shared_task(bind=True, ignore_result=True, max_retries=CANCEL_VERIFICATION_MAX_RETRIES)
def verify_task_run_cancelled_task(self, run_id: str, task_id: str, team_id: int, reason: str) -> None:
    """Deadline for a cancellation the run's workflow was signaled about but may never apply.

    Scheduled with a countdown by ``cancel_task_run``; idempotent, so a redelivery is harmless.
    Nothing else re-checks the run, so an unreachable Temporal has to be retried here or the run
    stays non-terminal for good.
    """
    from products.tasks.backend.facade.cancellation import (  # noqa: PLC0415 - keep temporalio off the celery import path
        force_terminalize_cancelled_run,
    )

    countdown = CANCEL_VERIFICATION_RETRY_DELAY_SECONDS * (2**self.request.retries)
    try:
        outcome = force_terminalize_cancelled_run(run_id, task_id, team_id, reason=reason)
    except Exception as error:
        raise self.retry(exc=error, countdown=countdown)

    # force_terminalize_cancelled_run reports outstanding work as an outcome instead of raising -
    # an unreachable workflow, or a cancelled run whose stream never closed - so the retry is
    # driven off the return value as well as off exceptions.
    if outcome == "unavailable":
        raise self.retry(
            exc=RuntimeError(f"Cancellation for task run {run_id} could not be completed"),
            countdown=countdown,
        )


@shared_task(ignore_result=True)
def dispatch_loop_run_terminal_notification_task(loop_id: str, team_id: int, event: str, payload: dict) -> None:
    from products.tasks.backend.logic.services.loop_runs import (  # noqa: PLC0415 (keep temporalio off the celery import path)
        dispatch_loop_run_terminal_notification,
    )

    dispatch_loop_run_terminal_notification(loop_id, team_id, event, payload)


@shared_task(ignore_result=True)
def refresh_stale_sandbox_custom_images_task() -> None:
    from products.tasks.backend.logic.services.custom_image_refresh import (  # noqa: PLC0415
        refresh_stale_sandbox_custom_images,
    )

    refresh_stale_sandbox_custom_images()
