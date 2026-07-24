"""
Celery-task wiring for the tasks product.

Re-exports the beat-scheduled loop sweeps that core's scheduler registers.
"""

from django.conf import settings

from celery import shared_task

from products.tasks.backend.loop_reconciliation import reconcile_loop_trigger_schedules_task
from products.tasks.backend.loop_retention import sweep_loop_task_retention_task

__all__ = ["reconcile_loop_trigger_schedules_task", "sweep_loop_task_retention_task"]


@shared_task(ignore_result=True)
def refresh_stale_sandbox_custom_images_task() -> None:
    from products.tasks.backend.logic.services.custom_image_refresh import (  # noqa: PLC0415
        refresh_stale_sandbox_custom_images,
    )

    refresh_stale_sandbox_custom_images()


@shared_task(ignore_result=True)
def bake_dev_stack_image_task() -> None:
    """Dispatch the nightly rebake of the prebaked PostHog dev-stack VM image."""
    if not settings.TASKS_DEV_STACK_IMAGE_BAKE_ENABLED:
        return

    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keeps the Temporal client off the import path
        execute_bake_dev_stack_image_workflow,
    )

    execute_bake_dev_stack_image_workflow()
