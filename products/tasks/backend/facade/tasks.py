"""
Celery-task wiring for the tasks product.

Re-exports the beat-scheduled loop sweeps that core's scheduler registers.
"""

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
    from products.tasks.backend.feature_flags import (
        is_dev_stack_image_bake_enabled,  # noqa: PLC0415 — keeps posthoganalytics off the import path
    )

    if not is_dev_stack_image_bake_enabled():
        return

    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keeps the Temporal client off the import path
        execute_bake_dev_stack_image_workflow,
    )

    execute_bake_dev_stack_image_workflow()


@shared_task(ignore_result=True)
def refresh_dev_stack_image_task() -> None:
    """Rebake the prebaked dev-stack image when the VM base image digest changes."""
    from products.tasks.backend.logic.services.dev_stack_image import (  # noqa: PLC0415 — keeps the service deps off the import path
        refresh_dev_stack_image_if_base_changed,
    )

    refresh_dev_stack_image_if_base_changed()
