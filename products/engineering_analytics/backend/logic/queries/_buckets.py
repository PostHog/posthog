"""Time bucketing shared by the windowed trend series, so they agree on grain and bucket alignment."""

from datetime import date, datetime, timedelta
from typing import Literal

Granularity = Literal["hour", "day", "week"]

_BUCKET_STEP: dict[Granularity, timedelta] = {
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
}


def bucket_expr(granularity: Granularity, column: str = "run_started_at") -> str:
    """ClickHouse truncation expression for ``column``. A week starts on Monday."""
    if granularity == "hour":
        return f"toStartOfHour({column})"
    if granularity == "day":
        return f"toStartOfDay({column})"
    return f"toStartOfWeek({column}, 1)"


def pick_granularity(date_from: datetime, date_to: datetime | None) -> Granularity:
    end = date_to or datetime.now(tz=date_from.tzinfo)
    span = end - date_from
    if span <= timedelta(hours=48):
        return "hour"
    if span <= timedelta(days=90):
        return "day"
    return "week"


def window_buckets(date_from: datetime, date_to: datetime | None, granularity: Granularity) -> list[datetime]:
    """Every bucket start across the window, oldest first, tz-naive like ``normalize_bucket``."""
    end = date_to or datetime.now(tz=date_from.tzinfo)
    start = normalize_bucket(date_from, granularity)
    end_aligned = normalize_bucket(end, granularity)
    if end_aligned < start:
        return []
    step = _BUCKET_STEP[granularity]
    buckets: list[datetime] = []
    current = start
    while current <= end_aligned:
        buckets.append(current)
        current += step
    return buckets


def normalize_bucket(value: datetime | date, granularity: Granularity) -> datetime:
    """The bucket start as a tz-naive datetime, so query rows and ``window_buckets`` key alike.

    Accepts a ``date`` because ClickHouse can return one for a truncated bucket.
    """
    naive = value.replace(tzinfo=None) if isinstance(value, datetime) else datetime(value.year, value.month, value.day)
    if granularity == "hour":
        return naive.replace(minute=0, second=0, microsecond=0)
    midnight = naive.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == "week":
        return midnight - timedelta(days=midnight.weekday())
    return midnight
