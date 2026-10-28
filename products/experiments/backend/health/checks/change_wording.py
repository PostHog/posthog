"""The words that the findings about flag changes after launch share. Pure functions, no I/O."""

from datetime import datetime, timedelta
from typing import Literal

from products.experiments.backend.health.context import (
    MAX_FLAG_SAVES,
    MAX_RELEASE_CONDITIONS,
    FlagHistoryNotCheckedReason,
)
from products.experiments.backend.health.split_changes import format_change_time

SECONDS_PER_DAY = 24 * 60 * 60


def suggested_start(changed_at: datetime, team_timezone: str) -> str:
    # The start date picker saves whole minutes, so a start inside the minute of the change keeps exposures
    # from before it.
    minute = changed_at.replace(second=0, microsecond=0)
    start = minute if minute == changed_at else minute + timedelta(minutes=1)
    return format_change_time(start, team_timezone)


def delay(
    *, launched_at: datetime, first_changed_at: datetime, exposed_before_first: bool | None, change_count: int
) -> list[str]:
    # When nobody knows whether anyone was exposed before the change, or the change came days after launch,
    # the time since launch tells the reader how many people the change can have moved.
    seconds = (first_changed_at - launched_at).total_seconds()
    if exposed_before_first is not None and seconds <= SECONDS_PER_DAY:
        return []
    change = "The change" if change_count == 1 else "The first change"
    return [f"{change} came {duration(seconds)} after launch."]


def the_change(change_count: int, determiner: Literal["the", "this"]) -> str:
    if change_count == 1:
        return f"{determiner} change"
    return "the changes" if determiner == "the" else "these changes"


def not_checked_because(reason: FlagHistoryNotCheckedReason) -> str:
    match reason:
        case FlagHistoryNotCheckedReason.EXPOSURE_FILTERS:
            return "the exposure criteria filter by properties"
        case FlagHistoryNotCheckedReason.EXPOSURE_ACTION:
            return "exposures come from an action"
        case FlagHistoryNotCheckedReason.EXPOSURE_CRITERIA:
            return "the exposure criteria can't be read"
        case FlagHistoryNotCheckedReason.NO_QUERY_ACCESS:
            return "this API key can't query events"
        case FlagHistoryNotCheckedReason.NO_HISTORY_ACCESS:
            return "you can't view the linked feature flag's history"
        case FlagHistoryNotCheckedReason.TOO_MANY_SAVES:
            return f"the flag was saved more than {MAX_FLAG_SAVES} times since launch"
        case FlagHistoryNotCheckedReason.TOO_MANY_CONDITIONS:
            return f"the flag has more than {MAX_RELEASE_CONDITIONS} release conditions"


def not_checked_next_step(reason: FlagHistoryNotCheckedReason, the_change: str) -> str:
    if reason == FlagHistoryNotCheckedReason.NO_QUERY_ACCESS:
        return f"Add the query:read scope to this API key, or review {the_change} in the flag history."
    return f"Review {the_change} in the flag history."


def duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "less than a minute"
    if minutes < 60:
        return _count(minutes, "minute")
    hours = minutes // 60
    if hours < 48:
        return _count(hours, "hour")
    return _count(hours // 24, "day")


def _count(value: int, unit: str) -> str:
    return f"{value} {unit}" if value == 1 else f"{value} {unit}s"
