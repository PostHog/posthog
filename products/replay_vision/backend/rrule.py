"""Local rrule helpers for scheduled vision actions.

Behaviorally identical to `products/workflows/backend/utils/rrule_utils.py` — copied rather
than imported so replay_vision doesn't take a cross-product dependency on the Workflows
backend just for date math. If these ever need to share an implementation, lift them into a
common module rather than wiring a product-to-product import.
"""

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
    """Compute the next `count` occurrences from an RRULE string.

    Expands the RRULE in naive local time so that e.g. "9 AM Europe/Prague" stays at 9 AM
    local across DST changes, then converts to UTC for storage.
    """
    tz = ZoneInfo(timezone_str)

    starts_local = starts_at.astimezone(tz).replace(tzinfo=None)
    rule = rrulestr(rrule_string, dtstart=starts_local, ignoretz=True)
    after_local = (after or datetime.now(UTC)).astimezone(tz).replace(tzinfo=None)

    occurrences: list[datetime] = []
    current = after_local
    for _ in range(count * 10):  # safety limit against unbounded gaps
        next_dt = rule.after(current, inc=False)
        if next_dt is None:
            break
        occurrences.append(next_dt.replace(tzinfo=tz).astimezone(UTC))
        if len(occurrences) >= count:
            break
        current = next_dt

    return occurrences
