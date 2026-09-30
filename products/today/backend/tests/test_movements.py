from datetime import date, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.logic.movements import biggest_movements, week_over_week

TODAY = date(2026, 9, 30)


def _daily(previous_per_day: float, current_per_day: float, days: int = 14) -> tuple[list[str], list[float]]:
    dates = [(TODAY - timedelta(days=offset)).isoformat() for offset in range(days, 0, -1)]
    values = [previous_per_day] * (days - 7) + [current_per_day] * 7
    # The current, incomplete day must never count.
    return [*dates, TODAY.isoformat()], [*values, 1000.0]


class TestWeekOverWeek(SimpleTestCase):
    def test_daily_series_compares_the_last_7_complete_days(self) -> None:
        days, data = _daily(10, 15)

        movement = week_over_week(label="Signups", interval="day", days=days, data=data, today=TODAY)

        assert movement is not None
        assert (movement.previous, movement.current, movement.pct_change) == (70, 105, 50.0)

    def test_weekly_series_skips_the_week_in_progress(self) -> None:
        weeks = ["2026-09-09", "2026-09-16", "2026-09-23", "2026-09-28"]

        movement = week_over_week(
            label="Spend", interval="week", days=weeks, data=[1, 2000, 1500, 999], today=TODAY
        )

        assert movement is not None
        assert (movement.previous, movement.current, movement.pct_change) == (2000, 1500, -25.0)

    @parameterized.expand(
        [
            ("too little data last week", "day", *_daily(1, 50)),
            ("hourly series are not compared", "hour", *_daily(10, 15)),
            ("no earlier week at all", "day", *_daily(10, 15, days=7)),
        ]
    )
    def test_returns_nothing_when_the_series_cannot_say(
        self, _name: str, interval: str, days: list[str], data: list[float]
    ) -> None:
        assert week_over_week(label="x", interval=interval, days=days, data=data, today=TODAY) is None

    def test_small_changes_are_left_out_and_the_rest_sorted_by_size(self) -> None:
        small = week_over_week(
            label="small", interval="day", days=_daily(100, 105)[0], data=_daily(100, 105)[1], today=TODAY
        )
        drop = week_over_week(
            label="drop", interval="day", days=_daily(100, 60)[0], data=_daily(100, 60)[1], today=TODAY
        )
        rise = week_over_week(
            label="rise", interval="day", days=_daily(100, 120)[0], data=_daily(100, 120)[1], today=TODAY
        )
        assert small and drop and rise

        assert [m.metric for m in biggest_movements([small, rise, drop])] == ["drop", "rise"]
