from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter  # type: ignore[import-untyped,unused-ignore]
from dateutil.relativedelta import relativedelta

from products.reminders.backend.constants import MAX_FIRES_PER_DAY

UTC_ZONE = ZoneInfo("UTC")


def resolve_timezone(tz_name: str | None) -> ZoneInfo:
    if not tz_name:
        return UTC_ZONE
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return UTC_ZONE


def _next_interval(current: datetime, interval: str) -> datetime:
    if interval == "daily":
        return current + relativedelta(days=1)
    if interval == "weekly":
        return current + relativedelta(weeks=1)
    if interval == "monthly":
        return current + relativedelta(months=1)
    if interval == "yearly":
        return current + relativedelta(years=1)
    raise ValueError(f"Unknown recurrence interval: {interval}")


def _next_cron(cron_expression: str, current: datetime, tz: ZoneInfo) -> datetime:
    reference = current.astimezone(tz)
    return croniter(cron_expression, reference).get_next(datetime).astimezone(UTC)


def compute_next_fire_at(
    current: datetime,
    *,
    interval: str | None,
    cron_expression: str | None,
    tz: ZoneInfo,
) -> datetime:
    if cron_expression:
        return _next_cron(cron_expression, current, tz)
    if interval:
        return _next_interval(current, interval)
    raise ValueError("Recurring reminder requires interval or cron_expression")


def exceeds_daily_frequency_cap(cron_expression: str) -> bool:
    # Count fires across a representative 24h window for every weekday, so a cron pinned
    # to a single day (e.g. "* * * * 2") can't slip past the cap by avoiding the samples.
    week_start = datetime(2026, 6, 15, 0, 0, tzinfo=UTC)  # Monday
    for offset in range(7):
        start = week_start + timedelta(days=offset)
        window_end = start + timedelta(days=1)
        # Seed just before the window so a fire landing exactly on `start` is counted
        # (croniter.get_next returns the first fire strictly after the seed).
        itr = croniter(cron_expression, start - timedelta(microseconds=1))
        fires = 0
        while True:
            nxt = itr.get_next(datetime)
            if nxt >= window_end:
                break
            fires += 1
            if fires > MAX_FIRES_PER_DAY:
                return True
    return False
