"""Reproduce synthetic holdout checks: python -m products.logs.backend.series_prediction_validation."""

import sys
import time
import argparse

import numpy as np

from posthog.dataclasses import frozen

from products.logs.backend.series_prediction import WeeklyPredictionBand


@frozen
class SyntheticSeries:
    counts: np.ndarray
    expected: np.ndarray


def generate_series(
    rng: np.random.Generator, *, weeks: int, interval_minutes: int, mean: float, cv: float, pattern: str
) -> SyntheticSeries:
    slots = 7 * 24 * 60 // interval_minutes
    hours = np.arange(slots) * interval_minutes / 60
    profile = np.ones(slots)
    if pattern in ("daily", "correlated", "bursty"):
        profile = 1 + 0.7 * np.sin(hours * np.pi / 12)
    elif pattern == "weekend":
        profile[hours >= 120] = 0.2
    elif pattern == "cron":
        profile[hours % 24 < 1] = 8
    expected = mean * interval_minutes / 60 * profile
    shape = (weeks + 1, slots)
    if pattern == "correlated":
        noise = np.zeros((weeks + 1) * slots)
        innovations = rng.normal(0, 0.25 * np.sqrt(1 - 0.7**2), noise.size)
        for index in range(1, noise.size):
            noise[index] = 0.7 * noise[index - 1] + innovations[index]
        counts = rng.poisson(np.tile(expected, weeks + 1) * np.exp(noise - 0.25**2 / 2)).reshape(shape)
    elif cv == 0:
        counts = rng.poisson(expected, size=shape)
    else:
        counts = rng.negative_binomial(1 / cv**2, 1 / (1 + expected * cv**2), size=shape)
    if pattern == "bursty":
        counts *= rng.choice([1, 3], size=shape, p=[0.98, 0.02])
    return SyntheticSeries(counts=counts, expected=expected)


@frozen
class ValidationCase:
    weeks: int
    interval_minutes: int
    mean: float
    cv: float
    pattern: str


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260918)
    args = parser.parse_args()
    if args.trials < 2:
        parser.error("--trials must be at least 2")
    cases = (
        [
            ValidationCase(weeks=weeks, interval_minutes=60, mean=mean, cv=cv, pattern="daily")
            for weeks in (4, 5)
            for mean in (5.0, 1000.0)
            for cv in (0.0, 0.12, 0.5, 2.2)
        ]
        + [
            ValidationCase(weeks=5, interval_minutes=60, mean=1000, cv=0.12, pattern=pattern)
            for pattern in ("flat", "weekend", "cron", "correlated", "bursty")
        ]
        + [
            ValidationCase(weeks=weeks, interval_minutes=grain, mean=1000, cv=0.12, pattern="daily")
            for weeks in (4, 5)
            for grain in (5, 15)
        ]
    )
    sys.stdout.write(
        "weeks,minutes,mean,cv,pattern,miss_rate,miss_se,spike_recall,drop_recall,mean_width_ratio,fit_ms\n"
    )
    passed = True
    for case in cases:
        rng = np.random.default_rng(args.seed)
        misses, spikes, drops, widths, durations = [], [], [], [], []
        for _trial in range(args.trials):
            sample = generate_series(
                rng,
                weeks=case.weeks,
                interval_minutes=case.interval_minutes,
                mean=case.mean,
                cv=case.cv,
                pattern=case.pattern,
            )
            started = time.perf_counter()
            band = WeeklyPredictionBand.fit(sample.counts[:-1])
            durations.append(time.perf_counter() - started)
            misses.append(float(np.mean((sample.counts[-1] < band.lower) | (sample.counts[-1] > band.upper))))
            spikes.append(float(np.mean(np.round(5 * sample.expected) > band.upper)))
            drops.append(float(np.mean(np.round(0.1 * sample.expected) < band.lower)))
            widths.append(float(np.mean((band.upper - band.lower) / sample.expected)))
        miss_rate = float(np.mean(misses))
        miss_se = float(np.std(misses, ddof=1) / np.sqrt(args.trials))
        passed &= miss_rate + 1.96 * miss_se <= 0.015
        if case.mean == 1000 and case.cv <= 0.12 and case.pattern != "bursty":
            passed &= bool(np.mean(spikes) >= 0.95 and np.mean(drops) >= 0.95)
        sys.stdout.write(
            f"{case.weeks},{case.interval_minutes},{case.mean},{case.cv},{case.pattern},"
            f"{miss_rate:.6f},{miss_se:.6f},{np.mean(spikes):.6f},{np.mean(drops):.6f},"
            f"{np.mean(widths):.3f},{1000 * np.mean(durations):.3f}\n"
        )
        sys.stdout.flush()
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
