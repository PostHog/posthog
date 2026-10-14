from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.logic.figures import numbers_in, same_amount


class TestFigures(SimpleTestCase):
    @parameterized.expand(
        [
            ("keeps a scaled range as one number", "about 18.6K–21.4K signups", ["18.6K–21.4K"]),
            ("keeps a percent range as one number", "17–21% of loads", ["17–21%"]),
            ("keeps a range with a sign on both ends as one number", "17%–21% of loads", ["17%–21%"]),
            ("adds a duration word only to a bare count", "for 40 minutes, then 1.3% weeks", ["40 minutes", "1.3%"]),
            ("skips numbers joined to other characters", "v1.2 at 10:30 for #123", []),
        ]
    )
    def test_finds_numbers(self, _name: str, text: str, expected: list[str]) -> None:
        assert [number.text for number in numbers_in(text)] == expected

    @parameterized.expand(
        [
            ("a rounded count covers the exact value", "1.35K users", "1,348 users", True),
            ("a rounded count stops at its rounding edge", "1.35K users", "1,356 users", False),
            ("a percent never matches a count", "12% of runs", "12 runs", False),
            ("a range matches only the same range", "40–90 runs", "40 runs", False),
        ]
    )
    def test_compares_amounts(self, _name: str, claim: str, source: str, expected: bool) -> None:
        assert same_amount(numbers_in(claim)[0].amount, numbers_in(source)[0].amount) is expected
