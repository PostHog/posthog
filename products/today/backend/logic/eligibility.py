"""Which day a briefing belongs to, and when the scheduler starts it."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from posthog.models import Team

# A briefing day starts at 8:00 local time; before that, yesterday's briefing is still the current one.
DAY_START_HOUR = 8


def resolve_timezone(name: str | None, team: Team) -> str:
    """The browser timezone when it is a valid name, else the project timezone."""
    for candidate in (name, team.timezone, "UTC"):
        if not candidate:
            continue
        try:
            ZoneInfo(candidate)
            return candidate
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return "UTC"


def briefing_day(now: datetime, timezone_name: str) -> date:
    local = now.astimezone(ZoneInfo(timezone_name))
    return (local - timedelta(hours=DAY_START_HOUR)).date()


def due_day(now: datetime, timezone_name: str, window_minutes: int) -> date | None:
    """The briefing day that starts within the next window, so the scheduler can write it before it starts."""
    soon = briefing_day(now + timedelta(minutes=window_minutes), timezone_name)
    return soon if soon != briefing_day(now, timezone_name) else None
