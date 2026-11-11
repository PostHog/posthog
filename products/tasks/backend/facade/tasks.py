"""
Celery-task wiring for the tasks product.

Re-exports the beat-scheduled tasks that core's scheduler registers.
"""

from products.tasks.backend.task_auto_archive import sweep_inactive_tasks_task
from products.tasks.backend.tasks.sandbox_images import (
    bake_dev_stack_image_task,
    refresh_dev_stack_image_task,
    refresh_stale_sandbox_custom_images_task,
)
from products.tasks.backend.tasks.tasks import settle_overdue_sandbox_compute_task, sweep_queued_gateway_usage

__all__ = [
    "bake_dev_stack_image_task",
    "refresh_dev_stack_image_task",
    "refresh_stale_sandbox_custom_images_task",
    "settle_overdue_sandbox_compute_task",
    "sweep_inactive_tasks_task",
    "sweep_queued_gateway_usage",
]
