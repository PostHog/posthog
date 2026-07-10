"""Workflow and activity registration lists for the stamphog Temporal worker.

Kept separate from ``temporal/__init__.py`` (owned elsewhere) so the worker wiring has a
stable import target: ``from products.stamphog.backend.temporal.registry import WORKFLOWS, ACTIVITIES``.
"""

from __future__ import annotations

from products.stamphog.backend.temporal.activities import (
    fetch_review_context,
    mark_review_failed,
    post_verdict,
    run_gates_activity,
    run_review_in_sandbox,
)
from products.stamphog.backend.temporal.workflow import StamphogReviewWorkflow

WORKFLOWS = [StamphogReviewWorkflow]

ACTIVITIES = [
    fetch_review_context,
    run_gates_activity,
    run_review_in_sandbox,
    post_verdict,
    mark_review_failed,
]

__all__ = ["WORKFLOWS", "ACTIVITIES"]
