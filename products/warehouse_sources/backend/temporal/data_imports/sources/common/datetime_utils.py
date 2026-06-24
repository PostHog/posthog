from datetime import UTC, date, datetime
from typing import Any


def coerce_datetime_to_utc(value: Any) -> datetime | None:
    """Normalize a date/datetime-like value to a timezone-aware UTC datetime.

    Returns None for anything that isn't a date or datetime. Naive datetimes are
    assumed to already be in UTC; aware datetimes are converted.
    """
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())

    if not isinstance(value, datetime):
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
