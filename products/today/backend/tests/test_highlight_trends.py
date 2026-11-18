from collections.abc import Sequence
from datetime import date, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.logic.highlight_trends import MAX_FILLED_DAYS, detect, fill_days, stale

TODAY = date(2026, 10, 13)


def days(values: Sequence[float]) -> list[tuple[date, float]]:
    start = TODAY - timedelta(days=len(values))
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def weeks(values: Sequence[float]) -> list[tuple[date, float]]:
    start = TODAY - timedelta(weeks=len(values) + 1)
    return [(start + timedelta(weeks=i), v) for i, v in enumerate(values)]


class TestHighlightTrends(SimpleTestCase):
    @parameterized.expand(
        [
            ("steady growth is not news", weeks([100, 110, 121, 133, 146, 161, 177, 195, 214]), "week", set()),
            ("a zero last period is not a drop", weeks([500, 520, 480, 510, 0]), "week", set()),
            ("a 5x jump is a level shift", weeks([200, 210, 190, 1000]), "week", {"level_shift"}),
            ("an issue that stops went quiet", days([400] * 25 + [0, 0, 0]), "day", {"went_quiet"}),
        ]
    )
    def test_detectors(self, _name: str, points: list[tuple[date, float]], period: str, expected: set[str]) -> None:
        found, _ = detect(points, period, TODAY)

        self.assertEqual({d.kind for d in found} & {"spike", "trend", "level_shift", "went_quiet"}, expected)

    @parameterized.expand(
        [
            (
                "a drop is measured against the same weekday",
                [1000.0] * 6 + [1010.0] + [1000.0] * 6 + [990.0] + [1000.0] * 13 + [500.0],
                [(True, -1)],
            ),
            (
                "a drop on a tiny metric is not news",
                [1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0] * 3 + [1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 0.0],
                [],
            ),
        ]
    )
    def test_same_weekday(self, _name: str, values: list[float], expected: list[tuple[bool, int]]) -> None:
        found, _ = detect(days(values), "day", TODAY)

        self.assertEqual([(d.same_weekday, d.direction) for d in found if d.kind == "same_weekday"], expected)

    @parameterized.expand(
        [
            ("daily data up to yesterday", days([5.0] * 10), "day", False),
            ("daily data that stopped a week ago", days([5.0] * 10)[:-7], "day", True),
            (
                "weekly data up to last week",
                [(TODAY - timedelta(weeks=w), 5.0) for w in range(6, 0, -1)],
                "week",
                False,
            ),
            ("weekly data that stopped a month ago", weeks([5.0] * 6)[:-2], "week", True),
        ]
    )
    def test_stale(self, _name: str, points: list[tuple[date, float]], period: str, expected: bool) -> None:
        self.assertEqual(stale(points, period, TODAY), expected)

    def test_filling_missing_days_stops_at_the_supported_lookback(self) -> None:
        points = [(date(1, 1, 1), 1.0), (TODAY - timedelta(days=2), 1.0), (TODAY - timedelta(days=1), 1.0)]

        filled = fill_days(points)

        self.assertEqual(
            (len(filled), filled[0][0]), (MAX_FILLED_DAYS + 1, TODAY - timedelta(days=1 + MAX_FILLED_DAYS))
        )
