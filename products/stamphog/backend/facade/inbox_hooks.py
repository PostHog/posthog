"""Hook that lets review_hog own the gate on re-reviewing self-driving inbox PRs.

review_hog's TaskRun receiver triggers the first review by calling ``queue_inbox_pr_review``, so
review_hog depends on stamphog. Importing review_hog back here, to re-check the assigned
reviewers' ``stamphog_review_inbox_prs`` toggles on later webhook deliveries and again when the
first review executes, would make that a cycle. Instead review_hog registers a resolver from its
``AppConfig.ready()``, and both Celery tasks call whatever is registered. With nothing registered (review_hog absent from
INSTALLED_APPS) the re-review gate fails closed: dismissal safety still runs, but no new review is
queued. Mirrors ``products/data_modeling/backend/facade/managed_viewset_hooks.py``.

Keep this module light. ``AppConfig.ready()`` imports it on the django.setup() path, so it must
never import Django models or heavy product internals.
"""

from __future__ import annotations

from collections.abc import Callable

# (team_id, signal_report_id, preferred_user_id) -> user id to attribute the review to when ANY assigned
# reviewer has the toggle on, else None. The preferred user wins while still opted in, so attribution stays
# stable across re-checks (the webhook leg prefers the task's creator, the receiver leg the reviewer it
# queued under). Both legs must gate the same way, or a push voids an approval and nothing replaces it.
InboxActingReviewerResolver = Callable[[int, str, int | None], int | None]

_inbox_acting_reviewer_resolver: InboxActingReviewerResolver | None = None


def register_inbox_acting_reviewer_resolver(fn: InboxActingReviewerResolver) -> None:
    global _inbox_acting_reviewer_resolver
    _inbox_acting_reviewer_resolver = fn


def get_inbox_acting_reviewer_resolver() -> InboxActingReviewerResolver | None:
    return _inbox_acting_reviewer_resolver
