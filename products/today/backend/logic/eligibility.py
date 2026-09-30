"""Who gets a briefing, and which day a briefing belongs to."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
import posthoganalytics

from posthog.models import Team, User

logger = structlog.get_logger(__name__)

FEATURE_FLAG = "today-rail-nav"
# A briefing day starts at 8:00 local time; before that, yesterday's briefing is still the current one.
DAY_START_HOUR = 8


def is_enabled_for(user: User, team: Team) -> bool:
    """Whether the new navigation (and so the briefing) is on for this person. Fails closed."""
    try:
        return (
            posthoganalytics.feature_enabled(
                FEATURE_FLAG,
                str(user.distinct_id),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={"organization": {"id": str(team.organization_id)}},
                person_properties={"email": user.email},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
            is True
        )
    except Exception:
        logger.warning("today_flag_check_failed", exc_info=True)
        return False


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
