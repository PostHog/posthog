from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr


def validate_rrule(rrule_string: str) -> None:
    """Validate an RRULE string. Raises ValueError if invalid."""
    if "DTSTART" in rrule_string:
        raise ValueError("RRULE must not contain DTSTART (starts_at is managed separately)")
    try:
        rrulestr(rrule_string)
    except TypeError as e:
        raise ValueError(str(e)) from e


def compute_next_occurrences(
    rrule_string: str,
    starts_at: datetime,
    timezone_str: str = "UTC",
    after: datetime | None = None,
    count: int = 1,
) -> list[datetime]:
    """
    Compute the next `count` occurrences from an RRULE string.

    Expands the RRULE in naive local time so that "9 AM Europe/Prague"
    stays at 9 AM local time across DST changes, then converts to UTC.
    """
    tz = ZoneInfo(timezone_str)

    # Convert starts_at to naive local time for RRULE expansion
    starts_local = starts_at.astimezone(tz).replace(tzinfo=None)

    rule = rrulestr(rrule_string, dtstart=starts_local, ignoretz=True)

    # Convert after to naive local time (default: now in target tz)
    after_local = (after or datetime.now(UTC)).astimezone(tz).replace(tzinfo=None)

    occurrences: list[datetime] = []
    current = after_local
    for _ in range(count * 10):  # Safety limit
        next_dt = rule.after(current, inc=False)
        if next_dt is None:
            break
        # Attach the target timezone (zoneinfo picks the correct DST offset
        # for this date), then convert to UTC for storage
        occurrences.append(next_dt.replace(tzinfo=tz).astimezone(UTC))
        if len(occurrences) >= count:
            break
        current = next_dt

    return occurrences
