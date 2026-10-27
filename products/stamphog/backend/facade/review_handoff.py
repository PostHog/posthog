"""Registry of reviewers that take over a self-driving pull request that stamphog refused.

A self-driving PR has no author to read a refusal, so a deeper review is the next step. The product
that runs that review registers a hook from its ``AppConfig.ready()``. Stamphog cannot import such a
product when that product already depends on stamphog, so the hook comes to stamphog through this
registry. Stamphog calls every hook after the refusal wins the run's terminal save, and a hook that
raises is logged and never fails the review. Mirrors ``finished_review_hooks.py``.

Keep this module light. ``AppConfig.ready()`` imports it on the django.setup() path, so it must
never import Django models or heavy product internals.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class RefusedSelfDrivingPullRequest:
    """A self-driving PR that stamphog refused or escalated."""

    team_id: int
    installation_id: str
    # Full name in "owner/repo" form.
    repository: str
    pr_number: int
    author_login: str
    head_branch: str


ReviewHandoffHook = Callable[[RefusedSelfDrivingPullRequest], None]

_review_handoff_hooks: list[ReviewHandoffHook] = []


def register_review_handoff_hook(fn: ReviewHandoffHook) -> None:
    # AppConfig.ready() can run more than once in one process, for example in tests.
    if fn not in _review_handoff_hooks:
        _review_handoff_hooks.append(fn)


def get_review_handoff_hooks() -> tuple[ReviewHandoffHook, ...]:
    return tuple(_review_handoff_hooks)
