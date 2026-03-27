from datetime import UTC, datetime

from unittest import TestCase

from parameterized import parameterized

from products.workflows.backend.utils.rrule_utils import compute_next_occurrences, validate_rrule


class TestRRuleUtils(TestCase):
    @parameterized.expand(
        [
            ("FREQ=WEEKLY;INTERVAL=1;BYDAY=MO",),
            ("FREQ=DAILY;COUNT=1",),
            ("FREQ=MONTHLY;BYMONTHDAY=15",),
            ("FREQ=MONTHLY;BYMONTHDAY=-1",),
            ("FREQ=YEARLY;INTERVAL=2",),
        ]
    )
    def test_validate_rrule_accepts_valid_strings(self, rrule_str):
        validate_rrule(rrule_str)

    @parameterized.expand(
        [
            ("NOT_A_RRULE",),
            ("FREQ=INVALID",),
            ("",),
            ("DTSTART:20260101T000000\nRRULE:FREQ=DAILY",),
            ("BYDAY=MO",),
        ]
    )
    def test_validate_rrule_rejects_invalid_strings(self, rrule_str):
        with self.assertRaises(ValueError):
            validate_rrule(rrule_str)

    def test_compute_next_occurrences_weekly(self):
        starts_at = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences(
            "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO", starts_at, timezone_str="UTC", after=starts_at, count=3
        )
        assert len(occurrences) == 3
        assert all(o.weekday() == 0 for o in occurrences)  # Monday

    def test_compute_next_occurrences_daily_count_1(self):
        starts_at = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences("FREQ=DAILY;COUNT=1", starts_at, after=starts_at, count=5)
        assert len(occurrences) == 0

    def test_compute_next_occurrences_monthly_last_day(self):
        starts_at = datetime(2030, 1, 31, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences(
            "FREQ=MONTHLY;BYMONTHDAY=-1", starts_at, timezone_str="UTC", after=starts_at, count=3
        )
        assert len(occurrences) == 3
        assert occurrences[0].day == 28  # Feb
        assert occurrences[1].day == 31  # Mar
        assert occurrences[2].day == 30  # Apr

    def test_compute_next_occurrences_with_until(self):
        starts_at = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences(
            "FREQ=DAILY;UNTIL=20300105T235959", starts_at, timezone_str="UTC", after=starts_at, count=10
        )
        assert len(occurrences) == 4

    def test_compute_next_occurrences_exhausted_rrule_returns_empty(self):
        starts_at = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences("FREQ=DAILY;COUNT=1", starts_at, timezone_str="UTC", count=5)
        assert len(occurrences) == 0

    def test_compute_next_occurrences_timezone_aware_dst(self):
        # starts_at is March 1 09:00 UTC = 10:00 CET (Prague winter time)
        starts_at = datetime(2030, 3, 1, 9, 0, 0, tzinfo=UTC)
        # Use a point before starts_at so March 1 is included
        after = datetime(2030, 2, 28, 0, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences(
            "FREQ=MONTHLY;BYMONTHDAY=1",
            starts_at,
            timezone_str="Europe/Prague",
            after=after,
            count=3,
        )
        assert len(occurrences) == 3
        # March: CET (UTC+1), 10:00 local -> 09:00 UTC
        assert occurrences[0].hour == 9
        # April: CEST (UTC+2), 10:00 local -> 08:00 UTC
        assert occurrences[1].hour == 8
        # May: still CEST
        assert occurrences[2].hour == 8

    def test_compute_next_occurrences_returns_utc(self):
        starts_at = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences(
            "FREQ=DAILY;COUNT=3", starts_at, timezone_str="US/Eastern", after=starts_at, count=5
        )
        for o in occurrences:
            assert o.tzinfo == UTC
