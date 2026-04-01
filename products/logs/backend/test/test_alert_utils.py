from datetime import UTC, datetime, timedelta

import pytest
from unittest import TestCase

from parameterized import parameterized

from products.logs.backend.alert_utils import advance_next_check_at


class TestAdvanceNextCheckAt(TestCase):
    @parameterized.expand(
        [
            (
                "schedule_relative_not_execution_relative",
                datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
                5,
                datetime(2026, 3, 19, 12, 7, tzinfo=UTC),
                # Schedule: :00, :05, :10. Ran at :07. Next future slot = :10 (not :12)
                datetime(2026, 3, 19, 12, 10, tzinfo=UTC),
            ),
            (
                "first_run_uses_now_plus_interval",
                None,
                1,
                datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 1, tzinfo=UTC),
            ),
            (
                "on_time_execution",
                datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
                1,
                datetime(2026, 3, 19, 12, 0, 30, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 1, tzinfo=UTC),
            ),
            (
                "skip_forward_after_downtime",
                datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
                1,
                datetime(2026, 3, 19, 12, 10, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 11, tzinfo=UTC),
            ),
            (
                "5_minute_interval",
                datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
                5,
                datetime(2026, 3, 19, 12, 3, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 5, tzinfo=UTC),
            ),
            (
                "5_minute_interval_skip_forward",
                datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
                5,
                datetime(2026, 3, 19, 12, 12, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 15, tzinfo=UTC),
            ),
        ]
    )
    def test_advance_next_check_at(
        self,
        _name: str,
        current_next_check_at: datetime | None,
        interval_minutes: int,
        now: datetime,
        expected: datetime,
    ) -> None:
        result = advance_next_check_at(current_next_check_at, interval_minutes, now)
        assert result == expected, f"Expected {expected}, got {result}"

    def test_next_check_is_always_in_the_future(self) -> None:
        now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
        result = advance_next_check_at(now, 1, now)
        assert result > now

    @parameterized.expand([(0,), (-1,), (-5,)])
    def test_rejects_non_positive_interval(self, interval: int) -> None:
        now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="must be positive"):
            advance_next_check_at(now, interval, now)

    def test_long_downtime_skips_correctly(self) -> None:
        scheduled = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
        now = scheduled + timedelta(hours=2)
        result = advance_next_check_at(scheduled, 1, now)
        assert result > now
        assert result <= now + timedelta(minutes=1)
