"""Inversion hook for the ReviewHog-owned gate on self-driving inbox PR re-reviews.

The initial review of a self-driving inbox PR is triggered by review_hog's TaskRun receiver
calling ``queue_inbox_pr_review`` — so review_hog depends on stamphog, and stamphog importing
review_hog back (to re-check the assigned reviewers' ``stamphog_review_inbox_prs`` toggles on
later webhook deliveries) would create a dependency cycle. Instead review_hog registers its
resolver at app-ready time (see its ``AppConfig.ready()``), and the webhook Celery task calls
through the registered callable. When nothing is registered (review_hog absent from
INSTALLED_APPS), the re-review gate fails closed: dismissal safety still runs, no new review
is queued. Mirrors ``products/data_modeling/backend/facade/managed_viewset_hooks.py``.

Kept LIGHT on purpose: this module is imported on the django.setup() path from
``AppConfig.ready()``, so it must never import Django models or heavy product internals.
"""

from __future__ import annotations

from collections.abc import Callable

# (team_id, signal_report_id, task_created_by_id) -> the user id to attribute the re-review to,
# when ANY of the report's assigned reviewers has the stamphog inbox toggle on; else None (nobody
# resolvable, or none of them opted in). The trigger leg must gate on the same rule — a resolver
# narrower than it would retract a standing approval as opted-out with somebody still opted in.
InboxActingReviewerResolver = Callable[[int, str, int | None], int | None]

_inbox_acting_reviewer_resolver: InboxActingReviewerResolver | None = None


def register_inbox_acting_reviewer_resolver(fn: InboxActingReviewerResolver) -> None:
    global _inbox_acting_reviewer_resolver
    _inbox_acting_reviewer_resolver = fn


def get_inbox_acting_reviewer_resolver() -> InboxActingReviewerResolver | None:
    return _inbox_acting_reviewer_resolver
