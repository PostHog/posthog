# Re-export tasks for Celery autodiscover
from products.visual_review.backend.tasks.tasks import (
    post_approval_comment,
    process_run_diffs,
    sweep_visual_review_artifacts,
    sweep_visual_review_runs,
    sync_rejection_comment,
)

__all__ = [
    "post_approval_comment",
    "process_run_diffs",
    "sweep_visual_review_artifacts",
    "sweep_visual_review_runs",
    "sync_rejection_comment",
]
