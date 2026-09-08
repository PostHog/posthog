"""Celery tasks core schedules for visual_review (see products/architecture.md, wiring couplings)."""

from products.visual_review.backend.tasks.tasks import sweep_visual_review_retention

__all__ = ["sweep_visual_review_retention"]
