"""
Celery-task wiring for the tasks product.

Re-exports the beat-scheduled loop sweeps that core's scheduler registers.
"""

from celery import shared_task

from products.tasks.backend.loop_reconciliation import reconcile_loop_trigger_schedules_task
from products.tasks.backend.loop_retention import sweep_loop_task_retention_task

__all__ = ["reconcile_loop_trigger_schedules_task", "sweep_loop_task_retention_task"]

# Retry budget for a PR-close cancellation: doubling from 30s, so the last attempt lands
# roughly 15 minutes out, which covers a transient Temporal or DB blip without a run
# whose PR is already closed sitting non-terminal for much longer than that.
CANCEL_WIZARD_RUN_MAX_RETRIES = 5
CANCEL_WIZARD_RUN_RETRY_DELAY_SECONDS = 30


@shared_task(bind=True, ignore_result=True, max_retries=CANCEL_WIZARD_RUN_MAX_RETRIES)
def cancel_wizard_run_on_pr_close_task(self, run_id: str, task_id: str, team_id: int, reason: str) -> None:
    """Cancel a wizard cloud run whose setup PR was closed without merging.

    The closing webhook is the only trigger: GitHub does not redeliver a delivery we answered
    2xx, and nothing else watches for a closed setup PR, so a transient failure has to be
    retried here or the cancellation is dropped for good. ``cancel_task_run`` is idempotent
    on an already-terminal run, so a retry or a redelivery is harmless.
    """
    from products.tasks.backend.facade.cancellation import (  # noqa: PLC0415 - keep temporalio off the celery import path
        cancel_task_run,
    )

    countdown = CANCEL_WIZARD_RUN_RETRY_DELAY_SECONDS * (2**self.request.retries)
    try:
        outcome, _ = cancel_task_run(run_id, task_id, team_id, reason=reason, source="pr_closed")
    except Exception as error:
        raise self.retry(exc=error, countdown=countdown)

    # cancel_task_run reports an undeliverable cancellation as an outcome instead of raising,
    # so the retry has to be driven off the return value as well as off exceptions.
    if outcome == "unavailable":
        raise self.retry(
            exc=RuntimeError(f"Cancellation for task run {run_id} could not be delivered"),
            countdown=countdown,
        )


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
def refresh_stale_sandbox_custom_images_task() -> None:
    from products.tasks.backend.logic.services.custom_image_refresh import (  # noqa: PLC0415
        refresh_stale_sandbox_custom_images,
    )

    refresh_stale_sandbox_custom_images()
