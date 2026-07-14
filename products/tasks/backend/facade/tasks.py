"""
Celery-task wiring for the tasks product.

Re-exports the beat-scheduled loop retention sweep that core's scheduler registers.
"""

from celery import shared_task

from products.tasks.backend.loop_retention import sweep_loop_task_retention_task

__all__ = ["sweep_loop_task_retention_task"]


@shared_task(ignore_result=True)
def refresh_stale_sandbox_custom_images_task() -> None:
    from products.tasks.backend.logic.services.custom_image_refresh import (  # noqa: PLC0415
        refresh_stale_sandbox_custom_images,
    )

    refresh_stale_sandbox_custom_images()
