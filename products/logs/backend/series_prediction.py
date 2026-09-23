import math

import numpy as np
from scipy import stats

from posthog.dataclasses import frozen

COVERAGE = 0.99
CALIBRATION_WEEKS = 2
MIN_HISTORY_WEEKS = CALIBRATION_WEEKS + 2


@frozen
class WeeklyPredictionBand:
    lower: np.ndarray
    upper: np.ndarray

    @classmethod
    def fit(cls, history: np.ndarray) -> "WeeklyPredictionBand":
        if history.ndim != 2 or history.shape[0] < MIN_HISTORY_WEEKS:
            raise ValueError("At least four complete weeks of history are required")
        if not np.all(np.isfinite(history)) or np.any(history < 0):
            raise ValueError("History must contain finite, nonnegative counts")

        training = history[:-CALIBRATION_WEEKS]
        calibration = history[-CALIBRATION_WEEKS:]
        means = np.mean(training, axis=0)
        variances = np.var(training, axis=0, ddof=1)
        dispersion = max(0.0, float(np.sum(variances - means))) / max(1.0, float(np.sum(means**2)))
        expected = np.maximum(
            (np.sum(training, axis=0) + np.mean(training) * dispersion) / (len(training) + dispersion), 1.0
        )
        if dispersion <= 1e-8:
            lower = stats.poisson.ppf(0.05, expected)
            upper = stats.poisson.ppf(0.95, expected)
        else:
            shape = 1.0 / dispersion
            probability = shape / (shape + expected)
            lower = stats.nbinom.ppf(0.05, shape, probability)
            upper = stats.nbinom.ppf(0.95, shape, probability)
        scores = np.maximum(np.log1p(lower) - np.log1p(calibration), np.log1p(calibration) - np.log1p(upper)).ravel()
        rank = math.ceil((scores.size + 1) * COVERAGE)
        if rank > scores.size:
            raise ValueError("Not enough calibration buckets for the requested coverage")
        expansion = np.maximum(
            float(np.partition(scores, rank - 1)[rank - 1]), -0.5 * (np.log1p(upper) - np.log1p(lower))
        )
        return cls(
            lower=np.floor(np.maximum(0.0, np.expm1(np.log1p(lower) - expansion))),
            upper=np.ceil(np.expm1(np.log1p(upper) + expansion)),
        )
