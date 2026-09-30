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


def local_day(now: datetime, timezone_name: str) -> date:
    return (now.astimezone(ZoneInfo(timezone_name)) - timedelta(hours=DAY_START_HOUR)).date()


def is_due(now: datetime, timezone_name: str, window_minutes: int) -> bool:
    """Whether local time is in the window just before the day starts."""
    local = now.astimezone(ZoneInfo(timezone_name))
    start = local.replace(hour=DAY_START_HOUR, minute=0, second=0, microsecond=0) - timedelta(minutes=window_minutes)
    return start <= local < start + timedelta(minutes=window_minutes)
