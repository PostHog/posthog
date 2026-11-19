from datetime import UTC, date, datetime, timedelta
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.incremental_start import (
    resolve_incremental_start,
)

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


class TestResolveIncrementalStart(SimpleTestCase):
    @parameterized.expand(
        [
            ("cursor_datetime", True, datetime(2026, 6, 1, tzinfo=UTC), {}, datetime(2026, 6, 1, tzinfo=UTC)),
            ("cursor_string", True, "2026-06-01T00:00:00Z", {}, datetime(2026, 6, 1, tzinfo=UTC)),
            ("cursor_naive_read_as_utc", True, datetime(2026, 6, 1), {}, datetime(2026, 6, 1, tzinfo=UTC)),
            ("cursor_epoch_zero_is_a_cursor", True, 0, {}, datetime(1970, 1, 1, tzinfo=UTC)),
            (
                "cursor_minus_lookback",
                True,
                datetime(2026, 6, 1, tzinfo=UTC),
                {"lookback": timedelta(hours=6)},
                datetime(2026, 5, 31, 18, 0, tzinfo=UTC),
            ),
            ("no_cursor_uses_default_window", True, None, {}, datetime(2026, 5, 16, 12, 0, tzinfo=UTC)),
            (
                "full_refresh_ignores_cursor",
                False,
                datetime(2026, 6, 1, tzinfo=UTC),
                {},
                datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
            ),
            (
                "lookback_not_applied_to_default",
                False,
                None,
                {"lookback": timedelta(days=5)},
                datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
            ),
            (
                "default_datetime",
                False,
                None,
                {"default": datetime(2020, 1, 1, tzinfo=UTC)},
                datetime(2020, 1, 1, tzinfo=UTC),
            ),
            (
                "floor_raises_cursor",
                True,
                datetime(2019, 1, 1, tzinfo=UTC),
                {"floor": datetime(2020, 1, 1, tzinfo=UTC)},
                datetime(2020, 1, 1, tzinfo=UTC),
            ),
            (
                "floor_date_raises_default",
                False,
                None,
                {"default": timedelta(days=3650), "floor": date(2020, 1, 1)},
                datetime(2020, 1, 1, tzinfo=UTC),
            ),
            (
                "floor_below_start_has_no_effect",
                True,
                datetime(2026, 6, 1, tzinfo=UTC),
                {"floor": date(2020, 1, 1)},
                datetime(2026, 6, 1, tzinfo=UTC),
            ),
            ("future_cursor_capped_at_now", True, datetime(2027, 1, 1, tzinfo=UTC), {}, NOW),
            ("future_floor_capped_at_now", False, None, {"floor": datetime(2027, 1, 1, tzinfo=UTC)}, NOW),
        ]
    )
    def test_start(
        self, _name: str, should_use: bool, last_value: Any, overrides: dict[str, Any], expected: datetime
    ) -> None:
        kwargs: dict[str, Any] = {"default": timedelta(days=30), "now": NOW, **overrides}
        assert resolve_incremental_start(should_use, last_value, **kwargs) == expected

    def test_naive_now_read_as_utc(self) -> None:
        start = resolve_incremental_start(False, None, default=timedelta(days=1), now=datetime(2026, 6, 15, 12, 0))
        assert start == datetime(2026, 6, 14, 12, 0, tzinfo=UTC)

    @parameterized.expand([("empty_string", ""), ("garbage", "not a date")])
    def test_unreadable_cursor_raises(self, _name: str, last_value: str) -> None:
        with self.assertRaises(ValueError):
            resolve_incremental_start(True, last_value, default=timedelta(days=30), now=NOW)
