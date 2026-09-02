from datetime import UTC, date, datetime
from typing import Any

from dateutil import parser as dateutil_parser


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


def parse_datetime_value(value: Any) -> datetime | None:
    """Same as `coerce_datetime_to_utc`, but also parses a datetime written as a string.

    An incremental watermark reaches a source as whatever the pipeline persisted, which is a
    string for some sources and a datetime for others, so a caller that has to compare one
    against a real datetime cannot assume either.
    """
    if isinstance(value, str):
        try:
            value = dateutil_parser.parse(value)
        except (ValueError, TypeError, OverflowError):
            return None
    return coerce_datetime_to_utc(value)
