from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    DatetimeStyle,
    EpochUnit,
    coerce_date,
    format_datetime,
    from_epoch,
    parse_datetime_value,
    to_epoch,
)

MOMENT = datetime(2024, 3, 5, 6, 7, 8, 123456, tzinfo=UTC)


class TestFormatDatetime(SimpleTestCase):
    @parameterized.expand(
        [
            ("iso_z", "2024-03-05T06:07:08Z"),
            ("iso_z_millis", "2024-03-05T06:07:08.123Z"),
            ("iso_z_micros", "2024-03-05T06:07:08.123456Z"),
            ("iso_offset", "2024-03-05T06:07:08+00:00"),
            ("iso_naive", "2024-03-05T06:07:08"),
            ("date", "2024-03-05"),
            ("compact_date", "20240305"),
        ]
    )
    def test_styles(self, style: DatetimeStyle, expected: str) -> None:
        assert format_datetime(MOMENT, style) == expected

    @parameterized.expand(
        [
            (
                "aware_non_utc_converted",
                datetime(2024, 3, 5, 1, 7, 8, tzinfo=timezone(timedelta(hours=-5))),
                "iso_z",
                "2024-03-05T06:07:08Z",
            ),
            ("naive_read_as_utc", datetime(2024, 3, 5, 6, 7, 8), "iso_z", "2024-03-05T06:07:08Z"),
            ("iso_string", "2024-03-05T06:07:08Z", "iso_z", "2024-03-05T06:07:08Z"),
            ("offset_string", "2024-03-05T08:07:08+02:00", "iso_z", "2024-03-05T06:07:08Z"),
            ("epoch_seconds", 1709618828, "iso_z", "2024-03-05T06:07:08Z"),
            ("epoch_millis", 1709618828123, "iso_z_millis", "2024-03-05T06:07:08.123Z"),
            ("date_is_midnight", date(2024, 3, 5), "iso_z", "2024-03-05T00:00:00Z"),
        ]
    )
    def test_inputs(self, _name: str, value: Any, style: DatetimeStyle, expected: str) -> None:
        assert format_datetime(value, style) == expected

    def test_millis_round_down_never_moves_past_the_value(self) -> None:
        assert format_datetime(datetime(2024, 12, 31, 23, 59, 59, 999999, tzinfo=UTC), "iso_z_millis") == (
            "2024-12-31T23:59:59.999Z"
        )

    @parameterized.expand([("garbage", "not a date"), ("none", None), ("empty", ""), ("bool", True)])
    def test_unreadable_value_raises(self, _name: str, value: Any) -> None:
        with self.assertRaises(ValueError):
            format_datetime(value)


class TestEpochConversion(SimpleTestCase):
    @parameterized.expand(
        [
            ("seconds", MOMENT, "s", 1709618828),
            ("millis", MOMENT, "ms", 1709618828123),
            ("millis_drop_micros", datetime(2024, 3, 5, 6, 7, 8, 999999, tzinfo=UTC), "ms", 1709618828999),
            ("seconds_before_1970_round_down", datetime(1969, 12, 31, 23, 59, 59, 500000, tzinfo=UTC), "s", -1),
            ("date", date(2024, 3, 5), "s", 1709596800),
            ("string", "2024-03-05T06:07:08.123456Z", "ms", 1709618828123),
        ]
    )
    def test_to_epoch(self, _name: str, value: Any, unit: EpochUnit, expected: int) -> None:
        assert to_epoch(value, unit) == expected

    @parameterized.expand(
        [
            ("int_seconds", 1709618828, "s", datetime(2024, 3, 5, 6, 7, 8, tzinfo=UTC)),
            ("int_millis_exact", 1709618828123, "ms", datetime(2024, 3, 5, 6, 7, 8, 123000, tzinfo=UTC)),
            ("float_seconds", 1709618828.5, "s", datetime(2024, 3, 5, 6, 7, 8, 500000, tzinfo=UTC)),
            ("int_string", "1709618828123", "ms", datetime(2024, 3, 5, 6, 7, 8, 123000, tzinfo=UTC)),
            ("float_string", "1709618828.5", "s", datetime(2024, 3, 5, 6, 7, 8, 500000, tzinfo=UTC)),
            ("negative", -1, "s", datetime(1969, 12, 31, 23, 59, 59, tzinfo=UTC)),
        ]
    )
    def test_from_epoch(self, _name: str, value: int | float | str, unit: EpochUnit, expected: datetime) -> None:
        result = from_epoch(value, unit)
        assert result == expected
        assert result.tzinfo == UTC

    def test_from_epoch_refuses_bool(self) -> None:
        with self.assertRaises(TypeError):
            from_epoch(True)


class TestParseDatetimeValue(SimpleTestCase):
    @parameterized.expand(
        [
            ("epoch_seconds", 1709618828, datetime(2024, 3, 5, 6, 7, 8, tzinfo=UTC)),
            ("epoch_seconds_float", 1709618828.25, datetime(2024, 3, 5, 6, 7, 8, 250000, tzinfo=UTC)),
            ("epoch_millis", 1709618828123, datetime(2024, 3, 5, 6, 7, 8, 123000, tzinfo=UTC)),
            ("largest_seconds", 99_999_999_999, datetime(5138, 11, 16, 9, 46, 39, tzinfo=UTC)),
            ("smallest_millis", 100_000_000_000, datetime(1973, 3, 3, 9, 46, 40, tzinfo=UTC)),
            ("zero_is_epoch", 0, datetime(1970, 1, 1, tzinfo=UTC)),
            ("string", "2024-03-05T06:07:08Z", datetime(2024, 3, 5, 6, 7, 8, tzinfo=UTC)),
            ("bool", True, None),
            ("nan", float("nan"), None),
            ("infinity", float("inf"), None),
            ("too_large", 10**20, None),
            ("garbage", "not a date", None),
        ]
    )
    def test_parse(self, _name: str, value: Any, expected: datetime | None) -> None:
        assert parse_datetime_value(value) == expected


class TestCoerceDate(SimpleTestCase):
    @parameterized.expand(
        [
            ("date", date(2024, 3, 5), date(2024, 3, 5)),
            (
                "datetime_in_utc_day",
                datetime(2024, 3, 5, 23, 0, tzinfo=timezone(timedelta(hours=-5))),
                date(2024, 3, 6),
            ),
            ("naive_datetime", datetime(2024, 3, 5, 23, 0), date(2024, 3, 5)),
            ("date_string", "2024-03-05", date(2024, 3, 5)),
            ("datetime_string", "2024-03-05T23:30:00-02:00", date(2024, 3, 6)),
            ("epoch_seconds", 1709618828, date(2024, 3, 5)),
            ("garbage", "not a date", None),
            ("none", None, None),
        ]
    )
    def test_coerce_date(self, _name: str, value: Any, expected: date | None) -> None:
        assert coerce_date(value) == expected
