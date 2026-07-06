import pytest

from parameterized import parameterized
from rest_framework import serializers

from products.tracing.backend.presentation.date_window import (
    normalize_tracing_date_range,
    normalize_tracing_window,
    parse_tracing_date_range_param,
)


class TestNormalizeTracingWindow:
    @parameterized.expand(
        [
            # Friendly shorthand is translated onto the global parser's tokens.
            # The headline case: lowercase "m" is minutes here (the global parser reads it as months).
            ("-30m", "-30M"),
            ("30m", "-30M"),
            ("-90s", "-90s"),
            ("-6h", "-6h"),
            ("-7d", "-7d"),
            ("-2w", "-2w"),
            # Units are case-insensitive; uppercase M stays minutes.
            ("-30M", "-30M"),
            ("-6H", "-6h"),
            # Whitespace is tolerated.
            (" -30m ", "-30M"),
        ]
    )
    def test_friendly_shorthand_is_normalized(self, value: str, expected: str) -> None:
        assert normalize_tracing_window(value) == expected

    @parameterized.expand(
        [
            # ISO 8601 timestamps pass through untouched.
            ("2026-06-26T14:55:00Z",),
            ("2026-06-26",),
            # The broader global relative grammar (boundaries, quarters, years) is preserved,
            # so anything that worked before keeps working — note "-1mStart" stays month-based.
            ("-1dStart",),
            ("wStart",),
            ("-3q",),
            ("-1y",),
            ("-1mStart",),
        ]
    )
    def test_supported_formats_pass_through_unchanged(self, value: str) -> None:
        assert normalize_tracing_window(value) == value.strip()

    @parameterized.expand([(None,), ("",), ("   ",)])
    def test_empty_values_return_none(self, value) -> None:
        assert normalize_tracing_window(value) is None

    @parameterized.expand(
        [
            ("soon",),
            ("-30 minutes",),
            ("last week",),
            ("-30x",),
            ("30",),
            # A bare unit with no number and no Start/End boundary would resolve to "now" in the
            # global parser — reject it rather than fail open. (Bare-unit-with-boundary like
            # "wStart" stays valid, covered above.)
            ("h",),
            ("-m",),
            ("d",),
        ]
    )
    def test_unparseable_values_raise(self, value: str) -> None:
        # The key behavior: garbage windows 400 instead of silently falling back to "now".
        with pytest.raises(serializers.ValidationError):
            normalize_tracing_window(value)


class TestNormalizeTracingDateRange:
    def test_missing_or_non_dict_uses_default(self) -> None:
        assert normalize_tracing_date_range(None) == {"date_from": "-1h"}
        assert normalize_tracing_date_range({}) == {"date_from": "-1h"}
        assert normalize_tracing_date_range("nonsense") == {"date_from": "-1h"}

    def test_respects_custom_default(self) -> None:
        assert normalize_tracing_date_range({}, default_date_from="-24h") == {"date_from": "-24h"}

    def test_normalizes_both_bounds(self) -> None:
        assert normalize_tracing_date_range({"date_from": "-30m", "date_to": "-5m"}) == {
            "date_from": "-30M",
            "date_to": "-5M",
        }

    def test_absent_date_to_is_dropped(self) -> None:
        result = normalize_tracing_date_range({"date_from": "-30m", "date_to": None})
        assert result == {"date_from": "-30M"}

    def test_invalid_bound_raises(self) -> None:
        with pytest.raises(serializers.ValidationError):
            normalize_tracing_date_range({"date_from": "-30 minutes"})


class TestParseTracingDateRangeParam:
    @parameterized.expand([(None,), ("",), ("   ",)])
    def test_absent_or_blank_uses_default(self, value) -> None:
        assert parse_tracing_date_range_param(value) == {"date_from": "-1h"}

    def test_respects_custom_default(self) -> None:
        assert parse_tracing_date_range_param(None, default_date_from="-24h") == {"date_from": "-24h"}

    def test_valid_json_object_is_normalized(self) -> None:
        assert parse_tracing_date_range_param('{"date_from": "-7d"}') == {"date_from": "-7d"}
        assert parse_tracing_date_range_param('{"date_from": "-30m", "date_to": "-5m"}') == {
            "date_from": "-30M",
            "date_to": "-5M",
        }

    @parameterized.expand(
        [
            # The headline bug: a bare relative string (the shape the sibling POST tools accept)
            # is not valid JSON — it must 400, not silently collapse to the default window.
            ("-7d",),
            ("banana",),
            # Valid JSON, but not an object — a bare scalar or array is not a date range.
            ("-7",),
            ("[]",),
            ('"-7d"',),
        ]
    )
    def test_unparseable_or_non_object_raises(self, value: str) -> None:
        with pytest.raises(serializers.ValidationError):
            parse_tracing_date_range_param(value)
