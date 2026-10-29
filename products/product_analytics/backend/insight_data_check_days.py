"""Which days of an insight's range the data checks read."""

from collections.abc import Mapping
from datetime import date, timedelta

from posthog.dataclasses import frozen


@frozen
class CheckWindow:
    days_in_range: list[date]
    # The newest days of the range, oldest first.
    days_to_check: list[date]
    # Estimated before the chart's filters, from the sizing sample.
    events_per_day: dict[date, int]

    @property
    def checks_whole_range(self) -> bool:
        return self.days_to_check == self.days_in_range

    @property
    def events_on_days_to_check(self) -> int:
        return sum(self.events_per_day[day] for day in self.days_to_check)


def days_between(first: date, last: date) -> list[date]:
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def newest_days_within(events_per_day: Mapping[date, int], budget: int) -> list[date]:
    chosen: list[date] = []
    total = 0
    for day in sorted(events_per_day, reverse=True):
        total += events_per_day[day]
        # The newest day is always checked, even when it alone is over the budget.
        if chosen and total > budget:
            break
        chosen.append(day)
    return sorted(chosen)
