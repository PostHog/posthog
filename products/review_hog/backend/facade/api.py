"""
Facade for review_hog — what other products may import.

Accept ids, call into the product's helpers, return plain values. Kept import-light: this can be
imported from other products' Celery tasks, and the heavy reviewer-resolution dependencies load at
call time inside the helpers it delegates to.
"""

from products.review_hog.backend.models import ReviewUserSettings
from products.review_hog.backend.receivers import resolve_assigned_inbox_reviewer


def resolve_stamphog_inbox_reviewer(team_id: int, signal_report_id: str, task_created_by_id: int | None) -> int | None:
    """The acting reviewer for a report's implementation PR, when their stamphog toggle is on.

    The re-check stamphog's webhook leg runs before re-reviewing a self-driving PR: same acting
    reviewer resolution as the inbox receiver (the report's suggested reviewers; the task creator
    when among them, else the first that resolves), gated on the CURRENT
    ``stamphog_review_inbox_prs`` value so switching the toggle off mid-PR stops new reviews.
    Returns the acting reviewer's user id, or None when nobody resolves or the toggle is off —
    approval dismissal must never key on this (safety is not preference-gated).
    """
    acting_user_id = resolve_assigned_inbox_reviewer(team_id, signal_report_id, task_created_by_id)
    if acting_user_id is None:
        return None
    if not ReviewUserSettings.load(team_id, acting_user_id).stamphog_review_inbox_prs:
        return None
    return acting_user_id
