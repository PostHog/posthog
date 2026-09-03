"""Why stamphog looked at a PR, derived from its provenance and the repo's review mode.

One rule, two Python callers: the API derives it for a stored run, and the invocation builder sends
it to the reviewer. A third expression of the same precedence lives in SQL
(``facade/api.py::_filter_by_trigger``) and cannot share this code, so that one stays hand-synced.
"""

from __future__ import annotations

from typing import Any

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


def trigger_for_run(*, output: dict[str, Any] | None, review_mode: ReviewMode | str) -> str:
    """The trigger to tell the reviewer, preferring what was stamped when the run was created.

    The reviewer reads this as fact in its trusted block, so it has to describe the delivery that
    admitted the run. Deriving it live would read a ``review_mode`` an admin may have changed since,
    and an ALL to LABEL switch would assert a request label the PR does not carry.

    Runs created before the stamp existed have nothing to read, so they derive it live as before.
    The facade deliberately keeps deriving instead of calling this: its display value is paired with
    a SQL filter that cannot read the stamp, and a display that disagreed with its own filter would
    hide rows the caller just saw.
    """
    stamped = (output or {}).get("review_trigger")
    if stamped:
        return str(stamped)
    return derive_review_trigger(
        has_inbox_review=bool((output or {}).get("inbox_review")), review_mode=review_mode
    ).value
