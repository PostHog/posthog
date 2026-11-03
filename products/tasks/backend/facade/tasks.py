"""
Celery-task wiring for the tasks product.

Re-exports tasks for core's scheduler and integration callbacks.
"""

from products.tasks.backend.github_recovery_tasks import resume_github_blocked_implementations
from products.tasks.backend.task_auto_archive import sweep_inactive_tasks_task
from products.tasks.backend.tasks.sandbox_images import (
    bake_dev_stack_image_task,
    refresh_dev_stack_image_task,
    refresh_stale_sandbox_custom_images_task,
)

__all__ = [
    "bake_dev_stack_image_task",
    "refresh_dev_stack_image_task",
    "refresh_stale_sandbox_custom_images_task",
    "resume_github_blocked_implementations",
    "sweep_inactive_tasks_task",
]
