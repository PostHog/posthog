"""
Celery-task wiring for the tasks product.

Re-exports the beat-scheduled loop sweeps that core's scheduler registers.
"""

import logging

from celery import shared_task

from products.tasks.backend.loop_reconciliation import reconcile_loop_trigger_schedules_task
from products.tasks.backend.loop_retention import sweep_loop_task_retention_task

__all__ = ["reconcile_loop_trigger_schedules_task", "sweep_loop_task_retention_task"]

logger = logging.getLogger(__name__)


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


@shared_task(ignore_result=True)
def bake_dev_stack_image_task() -> None:
    """Dispatch the nightly rebake of the prebaked PostHog dev-stack VM image."""
    from products.tasks.backend.feature_flags import (
        is_dev_stack_image_bake_enabled,  # noqa: PLC0415 — keeps posthoganalytics off the import path
    )

    if not is_dev_stack_image_bake_enabled():
        return

    from products.tasks.backend.metrics import (
        observe_dev_stack_image_bake,  # noqa: PLC0415 — keeps prometheus off the celery import path
    )
    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keeps the Temporal client off the import path
        execute_bake_dev_stack_image_workflow,
    )

    try:
        execute_bake_dev_stack_image_workflow(trigger="nightly")
    except Exception:
        # Without these, a Temporal-unreachable night is indistinguishable from the flag
        # being off in the bake metric. Re-raise so Celery still records the task failure.
        logger.exception("dev_stack_image_bake_dispatch_failed")
        observe_dev_stack_image_bake("dispatch_failed", trigger="nightly")
        raise


@shared_task(ignore_result=True)
def refresh_dev_stack_image_task() -> None:
    """Rebake the prebaked dev-stack image when the VM base image digest changes."""
    from products.tasks.backend.logic.services.dev_stack_image import (  # noqa: PLC0415 — keeps the service deps off the import path
        refresh_dev_stack_image_if_base_changed,
    )

    refresh_dev_stack_image_if_base_changed()
