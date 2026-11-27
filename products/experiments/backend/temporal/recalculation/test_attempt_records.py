"""Tests for the retry delays of the per-metric attempt records."""

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.experiments.backend.temporal.recalculation.attempt_records import _capacity_retry_delay_seconds


class TestCapacityRetryDelay(SimpleTestCase):
    @parameterized.expand(
        [
            ("first_attempt", 1, 10, 20),
            ("third_attempt", 3, 40, 80),
            ("beyond_the_cap", 7, 300, 300),
        ]
    )
    def test_band_doubles_per_attempt_up_to_the_cap(self, name: str, attempt: int, low: float, high: float):
        # The first retry must stay fast and the band must grow, or a brief contention costs minutes again
        # and a sustained one is polled constantly. The cap keeps the sum of the waits inside the metric's
        # schedule_to_close budget.
        with patch(
            "products.experiments.backend.temporal.recalculation.attempt_records.random.uniform", return_value=low
        ) as uniform:
            assert _capacity_retry_delay_seconds(attempt) == low
        uniform.assert_called_once_with(low, high)
