import datetime as dt

from parameterized import parameterized

from products.pulse.backend.models import PulseSubscriptionFrequency
from products.pulse.backend.temporal.period import period_bounds, period_key


class TestPeriodKey:
    @parameterized.expand(
        [
            # 2026-05-29 is a Friday in ISO week 22 of 2026
            ("weekly", PulseSubscriptionFrequency.WEEKLY, dt.datetime(2026, 5, 29, 14, 3, tzinfo=dt.UTC), "2026-W22"),
            ("daily", PulseSubscriptionFrequency.DAILY, dt.datetime(2026, 5, 29, 14, 3, tzinfo=dt.UTC), "2026-05-29"),
        ]
    )
    def test_period_key(self, _name, frequency, now, expected):
        assert period_key(now, frequency) == expected

    def test_weekly_key_is_stable_within_week(self):
        mon = dt.datetime(2026, 5, 25, 0, 0, tzinfo=dt.UTC)
        sun = dt.datetime(2026, 5, 31, 23, 59, tzinfo=dt.UTC)
        assert period_key(mon, PulseSubscriptionFrequency.WEEKLY) == period_key(sun, PulseSubscriptionFrequency.WEEKLY)

    def test_weekly_bounds_are_the_prior_iso_week(self):
        # 2026-05-29 is a Friday in ISO week 22; bounds snap to the prior completed week.
        now = dt.datetime(2026, 5, 29, 14, 3, tzinfo=dt.UTC)
        start, end = period_bounds(now, PulseSubscriptionFrequency.WEEKLY)
        assert start == dt.datetime(2026, 5, 18, tzinfo=dt.UTC)  # Monday of the prior week
        assert end == dt.datetime(2026, 5, 25, tzinfo=dt.UTC)  # Monday of this week
        assert (end - start) == dt.timedelta(days=7)

    def test_daily_bounds_are_the_prior_day(self):
        now = dt.datetime(2026, 5, 29, 14, 3, tzinfo=dt.UTC)
        start, end = period_bounds(now, PulseSubscriptionFrequency.DAILY)
        assert start == dt.datetime(2026, 5, 28, tzinfo=dt.UTC)
        assert end == dt.datetime(2026, 5, 29, tzinfo=dt.UTC)
        assert (end - start) == dt.timedelta(days=1)

    def test_bounds_are_stable_within_period(self):
        # Two instants in the same period must yield identical bounds, so the digest find-or-create
        # (which matches on these bounds) can't be fooled into a duplicate by the exact run time.
        mon = dt.datetime(2026, 5, 25, 8, 0, tzinfo=dt.UTC)
        fri = dt.datetime(2026, 5, 29, 14, 3, tzinfo=dt.UTC)
        assert period_bounds(mon, PulseSubscriptionFrequency.WEEKLY) == period_bounds(
            fri, PulseSubscriptionFrequency.WEEKLY
        )
        morning = dt.datetime(2026, 5, 29, 8, 0, tzinfo=dt.UTC)
        evening = dt.datetime(2026, 5, 29, 20, 30, tzinfo=dt.UTC)
        assert period_bounds(morning, PulseSubscriptionFrequency.DAILY) == period_bounds(
            evening, PulseSubscriptionFrequency.DAILY
        )
