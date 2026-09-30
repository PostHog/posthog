"""Week-over-week change of a trends series, from points that are already cached.

Only counts and sums are compared, because adding up a week of a rate or an average gives a
number that means nothing.
"""

from datetime import date, timedelta

from posthog.dataclasses import frozen

MIN_CHANGE_PCT = 10.0
MIN_PREVIOUS_WEEK = 20.0


@frozen
class Movement:
    metric: str
    previous: float
    current: float
    pct_change: float


def _points(days: list[str], data: list[float]) -> list[tuple[date, float]]:
    points = []
    for day, value in zip(days, data):
        try:
            points.append((date.fromisoformat(day[:10]), value))
        except ValueError:
            continue
    return points


def week_over_week(
    *, label: str, interval: str | None, days: list[str], data: list[float], today: date
) -> Movement | None:
    """The last complete week against the week before, or None when the series cannot say.

    Daily series compare the 7 days before today with the 7 days before those. Weekly series
    compare the last bucket that started at least 7 days ago with the bucket before it.
    """
    points = _points(days, data)
    if not points:
        return None
    if interval == "week":
        complete = [value for start, value in sorted(points) if start <= today - timedelta(days=7)]
        if len(complete) < 2:
            return None
        previous, current = complete[-2], complete[-1]
    elif interval in (None, "day"):
        by_day = dict(points)
        current = sum(by_day.get(today - timedelta(days=offset), 0.0) for offset in range(1, 8))
        previous = sum(by_day.get(today - timedelta(days=offset), 0.0) for offset in range(8, 15))
        if not any(today - timedelta(days=offset) in by_day for offset in range(8, 15)):
            return None
    else:
        return None
    if previous < MIN_PREVIOUS_WEEK:
        return None
    pct_change = (current - previous) / previous * 100
    return Movement(metric=label, previous=previous, current=current, pct_change=round(pct_change, 1))


def biggest_movements(movements: list[Movement]) -> list[Movement]:
    """Movements of at least the minimum size, biggest first."""
    return sorted(
        (movement for movement in movements if abs(movement.pct_change) >= MIN_CHANGE_PCT),
        key=lambda movement: -abs(movement.pct_change),
    )
