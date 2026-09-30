"""Which edition of which day a briefing belongs to, and when the scheduler starts it."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from posthog.dataclasses import frozen
from posthog.models import Team

from ..facade.enums import BriefingEdition

# A briefing day starts at 8:00 local time; before that, yesterday's midday briefing is still the current one.
DAY_START_HOUR = 8
MIDDAY_START_HOUR = 12


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


@frozen
class EditionSlot:
    """Which briefing is current: the day, and the morning or midday edition of it."""

    local_day: date
    edition: BriefingEdition


def current_edition(now: datetime, timezone_name: str) -> EditionSlot:
    local = now.astimezone(ZoneInfo(timezone_name))
    in_morning = DAY_START_HOUR <= local.hour < MIDDAY_START_HOUR
    return EditionSlot(
        local_day=(local - timedelta(hours=DAY_START_HOUR)).date(),
        edition=BriefingEdition.MORNING if in_morning else BriefingEdition.MIDDAY,
    )


def due_edition(now: datetime, timezone_name: str, window_minutes: int) -> EditionSlot | None:
    """The edition that starts within the next window, so the scheduler can write it before it starts."""
    soon = current_edition(now + timedelta(minutes=window_minutes), timezone_name)
    return soon if soon != current_edition(now, timezone_name) else None
