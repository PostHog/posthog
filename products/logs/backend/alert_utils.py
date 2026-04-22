from __future__ import annotations

from datetime import datetime, timedelta


def advance_next_check_at(
    current_next_check_at: datetime | None,
    check_interval_minutes: int,
    now: datetime,
) -> datetime:
    """Schedule-relative advancement. Skips forward past now if multiple intervals elapsed."""
    if check_interval_minutes <= 0:
        raise ValueError(f"check_interval_minutes must be positive, got {check_interval_minutes}")
    interval = timedelta(minutes=check_interval_minutes)

    if current_next_check_at is None:
        return now + interval

    next_at = current_next_check_at + interval
    if next_at <= now:
        elapsed = (now - next_at).total_seconds()
        intervals_to_skip = int(elapsed // interval.total_seconds()) + 1
        next_at += interval * intervals_to_skip
    return next_at
