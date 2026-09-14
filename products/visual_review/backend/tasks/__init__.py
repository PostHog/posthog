# Re-export tasks for Celery autodiscover
from products.visual_review.backend.tasks.tasks import (
    post_approval_comment,
    process_run_diffs,
    sweep_visual_review_retention,
)

__all__ = ["post_approval_comment", "process_run_diffs", "sweep_visual_review_retention"]
