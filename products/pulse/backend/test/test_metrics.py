from django.test import SimpleTestCase

from parameterized import parameterized

from products.pulse.backend.generation.metrics import per_day_rate


class TestMetrics(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty_window_is_zero_not_a_crash", [], 0.0),
            ("averages_over_values_read", [10.0, 20.0, 30.0], 20.0),
        ]
    )
    def test_per_day_rate(self, _name: str, values: list[float], expected: float) -> None:
        # The empty case guards the exported helper against ZeroDivisionError: a zero-day window
        # is a rate of zero, not an error.
        assert per_day_rate(values) == expected
