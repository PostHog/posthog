"""Facade re-export for the PostHog Review Temporal surface.

The worker registers ``WORKFLOWS``/``ACTIVITIES`` for the review task queue, and the schedule setup
creates the finding-outcomes schedule. Kept apart from ``facade/api.py`` so ``temporalio`` never
lands on the light data-surface import path.
"""

from products.review_hog.backend.temporal import ACTIVITIES, WORKFLOWS
from products.review_hog.backend.temporal.outcomes_schedule import create_review_hog_finding_outcomes_schedule

__all__ = ["ACTIVITIES", "WORKFLOWS", "create_review_hog_finding_outcomes_schedule"]
