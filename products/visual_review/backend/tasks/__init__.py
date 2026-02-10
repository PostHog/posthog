# Re-export tasks for Celery autodiscover
from products.visual_review.backend.tasks.tasks import process_run_diffs

__all__ = ["process_run_diffs"]
