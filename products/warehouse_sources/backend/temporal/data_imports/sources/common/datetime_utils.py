from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from dateutil import parser as dateutil_parser

DatetimeStyle = Literal["iso_z", "iso_z_millis", "iso_z_micros", "iso_offset", "iso_naive", "date", "compact_date"]
EpochUnit = Literal["s", "ms"]

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_EPOCH_UNITS: dict[EpochUnit, timedelta] = {"s": timedelta(seconds=1), "ms": timedelta(milliseconds=1)}

# 1e11 seconds is the year 5138, and 1e11 milliseconds is the year 1973, so a value at or above this
# bound is a timestamp in milliseconds.
_EPOCH_MILLIS_THRESHOLD = 100_000_000_000

_STRFTIME_FORMATS: dict[DatetimeStyle, str] = {
    "iso_z": "%Y-%m-%dT%H:%M:%SZ",
    "iso_z_micros": "%Y-%m-%dT%H:%M:%S.%fZ",
    "iso_offset": "%Y-%m-%dT%H:%M:%S+00:00",
    "iso_naive": "%Y-%m-%dT%H:%M:%S",
    "date": "%Y-%m-%d",
    "compact_date": "%Y%m%d",
}


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
    against a real datetime cannot assume either. A number returns None, and some sources rely
    on that to refuse a watermark of the wrong type; use `parse_datetime_or_epoch` to read one.
    """
    if isinstance(value, str):
        try:
            value = dateutil_parser.parse(value)
        except (ValueError, TypeError, OverflowError):
            return None
    return coerce_datetime_to_utc(value)


def parse_datetime_or_epoch(value: Any) -> datetime | None:
    """Same as `parse_datetime_value`, but also reads an epoch number.

    A number is an epoch timestamp in seconds, or in milliseconds when it is too large to be seconds.
    """
    if isinstance(value, int | float) and not isinstance(value, bool):
        unit: EpochUnit = "ms" if abs(value) >= _EPOCH_MILLIS_THRESHOLD else "s"
        try:
            return from_epoch(value, unit)
        except (ValueError, OverflowError):
            return None
    return parse_datetime_value(value)


def _require_datetime(value: Any) -> datetime:
    parsed = parse_datetime_or_epoch(value)
    if parsed is None:
        raise ValueError(f"Cannot read {value!r} as a datetime")
    return parsed


def format_datetime(value: Any, style: DatetimeStyle = "iso_z") -> str:
    """Write a datetime-like value in UTC in one of the formats that vendor APIs accept.

    A format with less precision than the value truncates it, so that a lower bound written with
    this function never moves past the row it names.
    """
    moment = _require_datetime(value)
    if style == "iso_z_millis":
        return f"{moment.strftime('%Y-%m-%dT%H:%M:%S')}.{moment.microsecond // 1000:03d}Z"
    return moment.strftime(_STRFTIME_FORMATS[style])


def to_epoch(value: Any, unit: EpochUnit = "s") -> int:
    """Return the epoch timestamp of a datetime-like value, rounded down to a whole `unit`."""
    return (_require_datetime(value) - _EPOCH) // _EPOCH_UNITS[unit]


def from_epoch(value: int | float | str, unit: EpochUnit = "s") -> datetime:
    if isinstance(value, bool):
        raise TypeError("An epoch timestamp cannot be a bool")
    if isinstance(value, str):
        value = float(value) if any(char in value for char in ".eE") else int(value)
    # Timedelta arithmetic keeps an integer timestamp exact, but float division does not.
    return _EPOCH + value * _EPOCH_UNITS[unit]


def coerce_date(value: Any) -> date | None:
    """Return the UTC calendar date of a date, a datetime, a datetime string or an epoch number.

    Returns None when the value cannot be read as a date.
    """
    parsed = parse_datetime_or_epoch(value)
    return parsed.date() if parsed is not None else None
