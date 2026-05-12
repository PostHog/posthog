from datetime import datetime, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from posthog.models.team.team import Team

from products.posthog_ai.backend.models import TrackedQuestion


def compute_next_run_at(cadence: str, anchor: datetime, team: Team) -> datetime:
    """Compute the next scheduled drift-check time for a watched question.

    Mirrors the alerts approach (posthog/tasks/alerts/utils.py:173-200):
    daily/weekly anchors land at a quiet hour in the team's timezone, monthly advances by one
    calendar month. UTC is returned.
    """
    team_timezone = pytz.timezone(team.timezone or "UTC")
    local_anchor = anchor.astimezone(team_timezone) if anchor.tzinfo is not None else team_timezone.localize(anchor)

    if cadence == TrackedQuestion.Cadence.DAILY:
        next_local = (local_anchor + relativedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)
    elif cadence == TrackedQuestion.Cadence.WEEKLY:
        next_local = (local_anchor + relativedelta(weeks=1)).replace(hour=3, minute=0, second=0, microsecond=0)
    elif cadence == TrackedQuestion.Cadence.MONTHLY:
        next_local = (local_anchor + relativedelta(months=1)).replace(hour=4, minute=0, second=0, microsecond=0)
    else:
        # Conservative fallback: weekly cadence rules.
        next_local = (local_anchor + relativedelta(weeks=1)).replace(hour=3, minute=0, second=0, microsecond=0)

    next_utc = next_local.astimezone(pytz.UTC)

    # Floor of "anchor + 1 minute" guards against bizarre clock states or DST round-trips that
    # would otherwise produce a next_run_at in the past.
    minimum_utc = (anchor.astimezone(pytz.UTC) if anchor.tzinfo else pytz.UTC.localize(anchor)) + timedelta(minutes=1)
    return max(next_utc, minimum_utc)
