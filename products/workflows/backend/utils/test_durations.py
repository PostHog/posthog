from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.utils.durations import duration_minutes, is_duration, is_signed_duration, parse_duration


class TestDurations(SimpleTestCase):
    @parameterized.expand(
        [
            ("whole", "10d", 10.0, "d", False),
            ("fractional", "1.5h", 1.5, "h", False),
            ("leading_point", ".5m", 0.5, "m", False),
            ("seconds", "45s", 45.0, "s", False),
            ("negative", "-1d", 1.0, "d", True),
        ]
    )
    def test_parses_a_duration(self, _name, value, amount, unit, negative):
        parsed = parse_duration(value)
        assert parsed is not None
        assert (parsed.amount, parsed.unit, parsed.negative) == (amount, unit, negative)

    @parameterized.expand(
        [
            ("no_unit", "10"),
            ("unsupported_unit", "10w"),
            ("uppercase_unit", "10D"),
            ("iso_8601", "P30D"),
            ("empty", ""),
            ("trailing_point", "5.d"),
            ("not_a_string", 1800),
            # Python's `\d` matches these and float() parses them, so a permissive grammar stores a
            # value the worker's ASCII parser rejects at runtime.
            ("arabic_indic_digits", "٥d"),
            ("fullwidth_digits", "１０d"),
            # `$` matches before a final newline, so these reach float() unless the match is anchored.
            ("trailing_newline", "1d\n"),
            ("signed_trailing_newline", "-1d\n"),
            ("leading_newline", "\n1d"),
        ]
    )
    def test_rejects_a_non_duration(self, _name, value):
        assert parse_duration(value) is None
        assert not is_duration(value)
        assert not is_signed_duration(value)

    def test_only_the_signed_check_accepts_a_negative(self):
        assert is_signed_duration("-1d")
        assert not is_duration("-1d")

    @parameterized.expand([("days", "2d", 2880.0), ("hours", "1.5h", 90.0), ("seconds", "30s", 0.5)])
    def test_converts_to_minutes(self, _name, value, minutes):
        assert duration_minutes(value) == minutes

    @parameterized.expand([("trailing_newline", "2d\n"), ("negative", "-2d"), ("not_a_duration", "2w")])
    def test_gives_no_minutes_for_a_non_duration(self, _name, value):
        assert duration_minutes(value) is None
