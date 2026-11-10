"""Registry of callbacks that hear about a stamphog review run once it reaches its outcome.

A product that asks stamphog for a review registers a callback from its ``AppConfig.ready()``, for
example to tell the person who asked how it went. Stamphog cannot import such a product when that
product already depends on stamphog, so the callback comes to stamphog through this registry.
Stamphog calls every callback after the run's terminal save, and a callback that raises is logged
and never fails the review. A superseded run calls nothing, because it has no outcome. Mirrors
``review_evidence.py``.

Keep this module light. ``AppConfig.ready()`` imports it on the django.setup() path, so it must
never import Django models or heavy product internals.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from .enums import ReviewRunStatus, ReviewVerdict


@dataclass(frozen=True, kw_only=True)
class FinishedReviewRun:
    """One review run's outcome. GATED and FAILED runs carry the verdict they stored."""

    run_id: UUID
    team_id: int
    repository: str
    pr_number: int
    status: ReviewRunStatus
    verdict: ReviewVerdict
    head_sha: str
    author_login: str
    head_branch: str
    # Not read off `verdict`, because a gate-blocked refusal stores WAIT.
    request_external_review: bool


FinishedReviewHook = Callable[[FinishedReviewRun], None]

_finished_review_hooks: list[FinishedReviewHook] = []


def register_finished_review_hook(fn: FinishedReviewHook) -> None:
    # AppConfig.ready() can run more than once in one process, for example in tests.
    if fn not in _finished_review_hooks:
        _finished_review_hooks.append(fn)


def get_finished_review_hooks() -> tuple[FinishedReviewHook, ...]:
    return tuple(_finished_review_hooks)
