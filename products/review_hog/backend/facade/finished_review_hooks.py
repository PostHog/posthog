"""Registry of callbacks that hear about a PostHog Review turn once it completes, or fails for good.

A product that asks for a review registers a callback from its ``AppConfig.ready()``, for example
to tell the person who asked how it went. review_hog cannot import such a product when that product
already depends on review_hog, so the callback comes here through this registry. A callback that
raises is logged and never fails the review. Mirrors ``products/stamphog/backend/facade/review_evidence.py``.

Keep this module light. ``AppConfig.ready()`` imports it on the django.setup() path, so it must
never import Django models or heavy product internals.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class FinishedReview:
    team_id: int
    report_id: str
    repository: str
    pr_number: int
    # REVIEW_MODE_FULL or REVIEW_MODE_FLASH, as the review request reported it.
    review_mode: str
    failed: bool
    # Valid findings of this turn. Zero for a failed turn.
    findings_count: int
    # False when the turn posted nothing on the pull request, for example a clean review.
    published: bool
    review_url: str


FinishedReviewHook = Callable[[FinishedReview], None]

_finished_review_hooks: list[FinishedReviewHook] = []


def register_finished_review_hook(fn: FinishedReviewHook) -> None:
    # AppConfig.ready() can run more than once in one process, for example in tests.
    if fn not in _finished_review_hooks:
        _finished_review_hooks.append(fn)


def get_finished_review_hooks() -> tuple[FinishedReviewHook, ...]:
    return tuple(_finished_review_hooks)
