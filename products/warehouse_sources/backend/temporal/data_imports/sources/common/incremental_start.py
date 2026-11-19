from datetime import UTC, date, datetime, timedelta
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
    parse_datetime_value,
)


def resolve_incremental_start(
    should_use: bool,
    last_value: Any,
    *,
    default: timedelta | datetime,
    lookback: timedelta | None = None,
    floor: datetime | date | None = None,
    now: datetime | None = None,
) -> datetime:
    """Return the UTC datetime where an incremental sync starts to read.

    With a cursor, the start is the cursor minus `lookback`. Without a cursor, the start is
    `default`, or `now` minus `default` when `default` is a timedelta. The start is then held
    between `floor` and `now`.

    A cursor of `0` or `""` is a real cursor, because only None means that no cursor exists.
    A cursor that cannot be read as a datetime raises ValueError, so that a sync does not
    silently read a different range.
    """
    current = coerce_datetime_to_utc(now) or datetime.now(UTC)

    if should_use and last_value is not None:
        start = parse_datetime_value(last_value)
        if start is None:
            raise ValueError(f"Cannot read the incremental cursor {last_value!r} as a datetime")
        if lookback is not None:
            start -= lookback
    elif isinstance(default, timedelta):
        start = current - default
    else:
        start = _as_utc(default)

    if floor is not None:
        start = max(start, _as_utc(floor))
    return min(start, current)


def _as_utc(value: datetime | date) -> datetime:
    converted = coerce_datetime_to_utc(value)
    assert converted is not None
    return converted
