"""Celery tasks core schedules for visual_review (see products/architecture.md, wiring couplings)."""

from products.visual_review.backend.tasks.tasks import send_visual_review_debt_digests, sweep_visual_review_retention

__all__ = ["send_visual_review_debt_digests", "sweep_visual_review_retention"]
