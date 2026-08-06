"""psycopg loaders shared by the SQL sources that stream over a psycopg connection.

Redshift speaks the Postgres wire protocol, so both the Postgres and Redshift drivers hit the
same psycopg edge cases: JSON that we want as a raw string, and date/time values outside Python's
representable range. Keeping the loaders here means both sources register identical behaviour
rather than drifting through copy-paste.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import (
    UTC,
    date,
    datetime,
    time as datetime_time,
    timezone,
)
from typing import Any

import psycopg
from psycopg.adapt import Loader
from psycopg.types.datetime import TimeLoader, TimestampLoader, TimestamptzLoader, TimetzLoader

__all__ = [
    "JsonAsStringLoader",
    "SafeDateLoader",
    "SafeTimeLoader",
    "SafeTimestampLoader",
    "SafeTimestamptzLoader",
    "SafeTimetzLoader",
]


class JsonAsStringLoader(Loader):
    def load(self, data):
        if data is None:
            return None
        return bytes(data).decode("utf-8")


class SafeDateLoader(Loader):
    """Load dates, handling edge cases beyond Python's date range.

    PostgreSQL (and Redshift, which shares the wire protocol) can store dates beyond Python's
    datetime.date limits (year 1 to year 9999). This includes 'infinity', '-infinity', and dates
    in years > 9999, which we clamp to Python's date limits rather than raising an error.

    Some Postgres-compatible engines (duckdb/duckgres) render a `date` in text
    mode with a trailing time component ("2022-04-01 00:00:00" or ISO "…T…") — we
    strip it before parsing. A value we genuinely cannot parse raises rather than
    being clamped: silently mapping it onto date.max fabricates a real-looking
    9999-12-31 and corrupts the whole column, which is far worse than a loud sync
    failure.
    """

    def load(self, data) -> date | None:
        if data is None:
            return None

        s = bytes(data).decode("utf-8").strip()

        if s in ("infinity", "-infinity"):
            return date.max if s == "infinity" else date.min

        # Handle negative years (BC dates)
        if s.startswith("-") or "bc" in s.lower():
            return date.min

        # Keep only the date portion — duckdb/duckgres may append a time or ISO "T".
        date_part = s.replace("T", " ").split(" ", 1)[0]

        try:
            year, month, day = (int(part) for part in date_part.split("-"))
        except ValueError as e:
            raise ValueError(f"Unparseable date value: {s!r}") from e

        if year > 9999:
            return date.max
        if year < 1:
            return date.min

        return date(year, month, day)


def _clamp_out_of_range_timestamp(data, *, tzinfo: timezone | None) -> datetime:
    """Map a timestamp value outside Python's datetime range onto datetime.min/max.

    PostgreSQL timestamps span years 4713 BC to 294276 AD and include 'infinity'/'-infinity',
    far wider than Python's datetime (year 1 to 9999). We pick the boundary by sign so values
    'before year 1' (BC dates, '-infinity', negative years) clamp low and everything else
    clamps high. `tzinfo` keeps the result aware/naive to match the column's Arrow type.
    """
    s = bytes(data).decode("utf-8", "replace").strip().lower()
    if s == "-infinity" or s.startswith("-") or "bc" in s:
        return datetime.min.replace(tzinfo=tzinfo)
    return datetime.max.replace(tzinfo=tzinfo)


class SafeTimestampLoader(TimestampLoader):
    """Load timestamps, handling values beyond Python's datetime range.

    psycopg's default loader raises `DataError` on timestamps outside Python's datetime
    range (years > 9999, 'infinity'/'-infinity'), which aborts the whole table sync. We
    defer to the default loader for in-range values and clamp the rest, mirroring
    `SafeDateLoader`. `timestamp` columns map to a naive Arrow type, so the clamp stays naive.
    """

    # psycopg short-circuits SQL NULL before the loader, so `data` is never None in practice;
    # the guard mirrors SafeDateLoader's defensive parity, hence the widened return + override ignore.
    def load(self, data) -> datetime | None:  # type: ignore[override]
        if data is None:
            return None
        try:
            return super().load(data)
        except psycopg.DataError:
            return _clamp_out_of_range_timestamp(data, tzinfo=None)


class SafeTimestamptzLoader(TimestamptzLoader):
    """`timestamptz` counterpart of `SafeTimestampLoader` (see its docstring).

    `timestamptz` columns map to a UTC-aware Arrow type, so the clamp is made tz-aware to
    avoid mixing naive and aware datetimes in the same Arrow column.
    """

    # See SafeTimestampLoader.load for why the override is widened/ignored.
    def load(self, data) -> datetime | None:  # type: ignore[override]
        if data is None:
            return None
        try:
            return super().load(data)
        except psycopg.DataError:
            return _clamp_out_of_range_timestamp(data, tzinfo=UTC)


def _clamp_pg_hour_24(data) -> bytes | None:
    """Clamp a '24:00:00' time/timetz value to the max Python time.

    PostgreSQL accepts '24:00:00' as the maximum value for the `time` and
    `timetz` types (end-of-day midnight), but Python's datetime.time caps the
    hour at 23. The time portion of an hour-24 value is always exactly
    '24:00:00', so we return an equivalent buffer with the time clamped to the
    maximum representable value, preserving any timezone suffix. Returns None
    for any value that is not an hour-24 time, so callers re-raise as usual.
    """
    s = bytes(data).decode("utf-8")
    if not s.startswith("24:"):
        return None
    rest = s[len("24:00:00") :]
    tz_suffix = ""
    for i, ch in enumerate(rest):
        if ch in "+-":
            tz_suffix = rest[i:]
            break
    return ("23:59:59.999999" + tz_suffix).encode("utf-8")


def _load_time_clamping_hour_24(super_load: Callable[[Any], datetime_time], data) -> datetime_time:
    """Run psycopg's default time loader, clamping the '24:00:00' edge case.

    Mirrors SafeDateLoader's clamp-to-max behaviour: an end-of-day
    '24:00:00' (which Python's datetime.time cannot represent) is clamped to
    time.max, while every other value — and any genuine parse error — is
    delegated to psycopg's default loader.
    """
    try:
        return super_load(data)
    except psycopg.DataError:
        clamped = _clamp_pg_hour_24(data)
        if clamped is None:
            raise
        return super_load(clamped)


class SafeTimeLoader(TimeLoader):
    """Load `time` values, clamping the '24:00:00' edge case."""

    def load(self, data) -> datetime_time:
        return _load_time_clamping_hour_24(super().load, data)


class SafeTimetzLoader(TimetzLoader):
    """Load `timetz` values, clamping '24:00:00' while preserving the timezone offset."""

    def load(self, data) -> datetime_time:
        return _load_time_clamping_hour_24(super().load, data)
