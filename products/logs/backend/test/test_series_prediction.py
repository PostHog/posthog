import pytest

import numpy as np
from parameterized import parameterized

from products.logs.backend.series_prediction import WeeklyPredictionBand


class TestWeeklyPredictionBand:
    @parameterized.expand([(4,), (5,)])
    def test_constant_seasonality_and_spike_drop_detection(self, weeks: int) -> None:
        expected = np.tile(np.concatenate((np.full(12, 100.0), np.full(12, 1000.0))), 7)
        history = np.tile(expected, (weeks, 1))
        band = WeeklyPredictionBand.fit(history)

        assert np.all(band.lower <= expected)
        assert np.all(band.upper >= expected)
        assert np.all(band.upper < expected * 1.5)
        assert np.all(band.lower > expected * 0.5)
        assert 500 > band.upper[0]
        assert 0 < band.lower[12]

    def test_calibration_observations_do_not_fit_the_forecast(self) -> None:
        history = np.full((5, 168), 100.0)
        history[-2:, :10] = 130.0
        band = WeeklyPredictionBand.fit(history)

        assert np.all((band.lower >= 74) & (band.lower <= 76))
        assert np.all((band.upper >= 130) & (band.upper <= 131))

    def test_uses_finite_sample_rank_without_interpolation(self) -> None:
        history = np.zeros((4, 168))
        history[-2:] = np.arange(336).reshape(2, 168)
        band = WeeklyPredictionBand.fit(history)

        np.testing.assert_array_equal(band.lower, np.zeros(168))
        assert np.all((band.upper >= 333) & (band.upper <= 334))

    def test_one_calibration_spike_does_not_widen_every_bucket(self) -> None:
        history = np.full((5, 168), 100.0)
        clean = WeeklyPredictionBand.fit(history)
        history[-1, 0] = 100000.0
        band = WeeklyPredictionBand.fit(history)

        np.testing.assert_array_equal(band.lower, clean.lower)
        np.testing.assert_array_equal(band.upper, clean.upper)

    def test_training_outlier_does_not_make_all_other_slots_uninformative(self) -> None:
        history = np.full((5, 168), 100.0)
        history[0, 0] = 100000.0
        band = WeeklyPredictionBand.fit(history)

        assert np.all(band.upper[1:] < 200)
        assert np.all(band.lower[1:] > 0)
        assert np.all(band.lower <= band.upper)

    @parameterized.expand(
        [
            ("short", np.ones((3, 168))),
            ("too_few_buckets", np.ones((4, 24))),
            ("negative", np.full((4, 168), -1.0)),
            ("missing", np.full((4, 168), np.nan)),
            ("infinite", np.full((4, 168), np.inf)),
        ]
    )
    def test_rejects_unsupported_history(self, _name: str, history: np.ndarray) -> None:
        with pytest.raises(ValueError):
            WeeklyPredictionBand.fit(history)

    @parameterized.expand(
        [(weeks, mean, cv) for weeks in (4, 5) for mean in (5.0, 1000.0) for cv in (0.0, 0.12, 0.5, 2.2)]
    )
    def test_held_out_week_coverage(self, weeks: int, mean: float, cv: float) -> None:
        rng = np.random.default_rng(8143)
        profile = np.tile(1.0 + 0.7 * np.sin(np.arange(24) * np.pi / 12), 7)
        means = mean * profile
        outside = []
        for _trial in range(128):
            counts = (
                rng.poisson(means, size=(weeks + 1, 168))
                if cv == 0
                else rng.negative_binomial(1 / cv**2, 1 / (1 + means * cv**2), size=(weeks + 1, 168))
            )
            band = WeeklyPredictionBand.fit(counts[:-1])
            outside.append(float(np.mean((counts[-1] < band.lower) | (counts[-1] > band.upper))))
            if mean == 1000 and cv <= 0.12:
                assert np.mean(5 * means > band.upper) > 0.95
                assert np.mean(0.1 * means < band.lower) > 0.95
        assert float(np.mean(outside)) < 0.015, (weeks, mean, cv, np.mean(outside))
