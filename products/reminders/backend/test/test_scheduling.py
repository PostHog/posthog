from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from parameterized import parameterized

from products.reminders.backend.scheduling import compute_next_fire_at, exceeds_daily_frequency_cap, resolve_timezone


class TestComputeNextFireAt(SimpleTestCase):
    @parameterized.expand(
        [
            ("daily", datetime(2026, 6, 15, 9, 0, tzinfo=UTC), datetime(2026, 6, 16, 9, 0, tzinfo=UTC)),
            ("weekly", datetime(2026, 6, 15, 9, 0, tzinfo=UTC), datetime(2026, 6, 22, 9, 0, tzinfo=UTC)),
        ]
    )
    def test_interval_advances(self, interval: str, current: datetime, expected: datetime) -> None:
        result = compute_next_fire_at(current, interval=interval, cron_expression=None, tz=ZoneInfo("UTC"))
        self.assertEqual(result, expected)

    def test_cron_resolves_in_timezone(self) -> None:
        # 9am weekdays in New York (UTC-4 in June) => 13:00 UTC
        current = datetime(2026, 6, 15, 13, 0, tzinfo=UTC)  # a Monday
        result = compute_next_fire_at(
            current, interval=None, cron_expression="0 9 * * 1-5", tz=ZoneInfo("America/New_York")
        )
        self.assertEqual(result, datetime(2026, 6, 16, 13, 0, tzinfo=UTC))


class TestDailyFrequencyCap(SimpleTestCase):
    @parameterized.expand(
        [
            ("0 9 * * *", False),
            ("0 9,12,15,18 * * *", False),
            ("0 9,12,15,18,21 * * *", True),
            ("*/30 * * * *", True),
            ("* * * * *", True),
            ("0 0,6,12,18 * * *", False),  # 4 fires including midnight => at cap, allowed
            ("0 0,6,12,18,23 * * *", True),  # 5 fires including midnight => over cap, rejected
            ("* * * * 2", True),  # every minute, Tuesdays only => must not slip the cap
            ("*/10 * * * 4", True),  # every 10 min, Thursdays only => over cap
            ("0 9 * * 3", False),  # once on Wednesdays => within cap
        ]
    )
    def test_cron_frequency(self, cron_expression: str, expected_exceeds: bool) -> None:
        self.assertEqual(exceeds_daily_frequency_cap(cron_expression), expected_exceeds)


class TestResolveTimezone(SimpleTestCase):
    @parameterized.expand(
        [
            (None, "UTC"),
            ("", "UTC"),
            ("Mars/Phobos", "UTC"),
            ("America/New_York", "America/New_York"),
        ]
    )
    def test_resolve_timezone(self, tz_name: str | None, expected: str) -> None:
        self.assertEqual(resolve_timezone(tz_name), ZoneInfo(expected))
