"""Shared time-bucketing helpers for the windowed trend series.

The per-bucket history adapts its granularity to the window length (hour / day / week)
so a trend keeps a readable number of points — per-day buckets are useless for a 24h
window and far too many for a year. Used by the workflow-health sparkline and the repo
hub's cost-per-merge series, so the two agree on grain and bucket alignment.
"""

from datetime import date, datetime, timedelta
from typing import Literal

Granularity = Literal["hour", "day", "week"]

_BUCKET_STEP: dict[Granularity, timedelta] = {
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
}


def bucket_expr(granularity: Granularity, column: str = "run_started_at") -> str:
    """ClickHouse truncation expression for ``column`` at ``granularity``. Week starts Monday (mode 1)."""
    if granularity == "hour":
        return f"toStartOfHour({column})"
    if granularity == "day":
        return f"toStartOfDay({column})"
    return f"toStartOfWeek({column}, 1)"


def pick_granularity(date_from: datetime, date_to: datetime | None) -> Granularity:
    """Hour for short windows, week for long ones — keeps the series at a readable point count."""
    end = date_to or datetime.now(tz=date_from.tzinfo)
    span = end - date_from
    if span <= timedelta(hours=48):
        return "hour"
    if span <= timedelta(days=90):
        return "day"
    return "week"


def window_buckets(date_from: datetime, date_to: datetime | None, granularity: Granularity) -> list[datetime]:
    """Every bucket start across the window, oldest first — the zero-fill spine a sparse series maps onto."""
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
    """Align a timestamp to its bucket start, tz-naive, so query rows and the zero-fill spine key alike.

    ClickHouse can hand the bucket back as a ``date`` (date/week truncation) or a ``datetime``
    (hour truncation); widen the former so both sides key on the same type.
    """
    naive = value.replace(tzinfo=None) if isinstance(value, datetime) else datetime(value.year, value.month, value.day)
    if granularity == "hour":
        return naive.replace(minute=0, second=0, microsecond=0)
    midnight = naive.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == "week":
        return midnight - timedelta(days=midnight.weekday())
    return midnight
