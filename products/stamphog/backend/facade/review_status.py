"""Hook that lets an automated code reviewer tell stamphog where its review of a PR head stands.

ReviewHog (PostHog Review) depends on stamphog, so stamphog cannot import it to ask. Instead the
reviewer registers a provider from its ``AppConfig.ready()``, and stamphog's review workflow calls
whatever is registered. With nothing registered, or when the provider raises, stamphog reviews as if
no automated review exists: it neither waits for one nor counts one as assurance.
Mirrors ``inbox_hooks.py``.

Keep this module light. ``AppConfig.ready()`` imports it on the django.setup() path, so it must
never import Django models or heavy product internals.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class ReviewStatusState(StrEnum):
    # Accepted but not started, or running. A turn stays pending until its findings are on the PR.
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, kw_only=True)
class ReviewStatus:
    """Where one automated review of one PR head stands."""

    state: ReviewStatusState
    # The name people see on the PR, for example "PostHog Review".
    reviewer: str
    # The review depth as people see it, for example "Standard" or "Deep".
    review_kind: str
    # Valid findings of a completed review. Zero while pending or failed.
    findings_count: int
    # True when the review posted on the PR. A clean review posts nothing, so it stays False.
    published: bool
    head_sha: str


# (repository "owner/name", pr_number, head_sha) -> the status of the review of exactly that head,
# or None when no review of that head is known.
ReviewStatusProvider = Callable[[str, int, str], ReviewStatus | None]

_review_status_provider: ReviewStatusProvider | None = None


def register_review_status_provider(fn: ReviewStatusProvider) -> None:
    global _review_status_provider
    _review_status_provider = fn


def get_review_status_provider() -> ReviewStatusProvider | None:
    return _review_status_provider
