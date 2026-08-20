"""Why stamphog looked at a PR, derived from its provenance and the repo's review mode.

One rule, two Python callers: the API derives it for a stored run, and the invocation builder sends
it to the reviewer. A third expression of the same precedence lives in SQL
(``facade/api.py::_filter_by_trigger``) and cannot share this code, so that one stays hand-synced.
"""

from __future__ import annotations

from ..facade.enums import ReviewMode, ReviewTrigger


def derive_review_trigger(*, has_inbox_review: bool, review_mode: ReviewMode | str) -> ReviewTrigger:
    """Inbox provenance outranks the repo mode.

    A self-driving run is dispatched from the inbox whether or not the repo also reviews every PR
    event, so a repo in ALL mode still reports SELF_DRIVING for those PRs.
    """
    if has_inbox_review:
        return ReviewTrigger.SELF_DRIVING
    if review_mode == ReviewMode.LABEL:
        return ReviewTrigger.LABEL
    return ReviewTrigger.ALL
