"""Which days of an insight's range the data checks read."""

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from posthog.dataclasses import frozen

from products.product_analytics.backend.facade.contracts import InsightDataCheckedPeriod


@frozen
class CheckWindow:
    days_in_range: list[date]
    days_to_check: list[date]
    # Estimated before the chart's filters, from the sizing sample.
    events_per_day: dict[date, int]

    @property
    def checks_whole_range(self) -> bool:
        return self.days_to_check == self.days_in_range

    @property
    def events_on_days_to_check(self) -> int:
        return sum(self.events_per_day[day] for day in self.days_to_check)

    @property
    def range_scale(self) -> float:
        """How many events the whole range holds for each event on the checked days."""
        if self.checks_whole_range or not self.events_on_days_to_check:
            return 1.0
        return sum(self.events_per_day.values()) / self.events_on_days_to_check


def days_between(first: date, last: date) -> list[date]:
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def days_to_size(days: Sequence[date], limit: int) -> list[date]:
    """An even spread of at most `limit` days that always includes the first and last day."""
    if len(days) <= limit:
        return list(days)
    step = (len(days) - 1) / (limit - 1)
    return sorted({days[round(index * step)] for index in range(limit)})


def _nearest_day(day: date, sorted_days: Sequence[date]) -> date:
    index = bisect_left(sorted_days, day)
    neighbours = sorted_days[max(index - 1, 0) : index + 1]
    return min(neighbours, key=lambda neighbour: abs((neighbour - day).days))


def estimate_events_per_day(days: Sequence[date], sized_events: Mapping[date, int]) -> dict[date, int]:
    """Every day's events, where a day that was not sized takes the size of the nearest day that was."""
    sized_days = sorted(sized_events)
    return {day: sized_events[_nearest_day(day, sized_days)] for day in days}


def _newest_days_within(days: Sequence[date], events_per_day: Mapping[date, int], budget: int) -> list[date]:
    chosen: list[date] = []
    total = 0
    for day in reversed(days):
        total += events_per_day[day]
        # The newest day is always checked, even when it alone is over the budget.
        if chosen and total > budget:
            break
        chosen.append(day)
    return chosen


def _evenly_spread_days_within(days: Sequence[date], events_per_day: Mapping[date, int], budget: int) -> list[date]:
    if not days or budget <= 0:
        return []
    average = sum(events_per_day[day] for day in days) / len(days)
    count = len(days) if average == 0 else min(len(days), int(budget // average))
    if count == 0:
        return []

    step = len(days) / count
    chosen: list[date] = []
    total = 0
    for day in (days[int((index + 0.5) * step)] for index in range(count)):
        if total + events_per_day[day] > budget:
            continue
        chosen.append(day)
        total += events_per_day[day]
    return chosen


def choose_days_to_check(events_per_day: Mapping[date, int], budget: int) -> list[date]:
    days = sorted(events_per_day)
    if sum(events_per_day.values()) <= budget:
        return days

    # Half the budget goes to the newest days, because a problem there is one people can still fix.
    newest = _newest_days_within(days, events_per_day, budget // 2)
    older = days[: len(days) - len(newest)]
    spread_budget = budget - sum(events_per_day[day] for day in newest)
    return sorted([*_evenly_spread_days_within(older, events_per_day, spread_budget), *newest])


def periods_of(days: Sequence[date]) -> list[InsightDataCheckedPeriod]:
    """Runs of consecutive days, so a long stretch of checked days reads as one period."""
    periods: list[InsightDataCheckedPeriod] = []
    for day in sorted(days):
        if periods and periods[-1].date_to + timedelta(days=1) == day:
            periods[-1] = InsightDataCheckedPeriod(date_from=periods[-1].date_from, date_to=day)
        else:
            periods.append(InsightDataCheckedPeriod(date_from=day, date_to=day))
    return periods
