import math

import pytest

from parameterized import parameterized

from products.experiments.backend.running_time_calculator import (
    BaselineStats,
    calculate_baseline_value,
    calculate_detectable_effect,
    calculate_running_time_days,
    calculate_sample_size,
    calculate_variance,
    calculate_variance_from_stats,
)


class TestCalculateBaselineValue:
    @parameterized.expand(
        [
            # mean total count: avg events per user = sum / samples
            ("mean_count", BaselineStats(number_of_samples=14000, sum=56000, step_counts=[]), 4),
            # mean sum: avg property value per user
            ("mean_sum_or_avg", BaselineStats(number_of_samples=14000, sum=700000, step_counts=[]), 50),
            # funnel: conversion rate = final step / samples
            ("funnel", BaselineStats(number_of_samples=1000, sum=100, step_counts=[1000, 100]), 0.1),
        ]
    )
    def test_baseline_value(self, metric_type, baseline, expected):
        assert calculate_baseline_value(baseline, metric_type) == expected

    def test_funnel_falls_back_to_sum_when_no_step_counts(self):
        baseline = BaselineStats(number_of_samples=1000, sum=100, step_counts=[])
        assert calculate_baseline_value(baseline, "funnel") == 0.1

    def test_ratio_uses_denominator_sum(self):
        baseline = BaselineStats(number_of_samples=10000, sum=500000, denominator_sum=50000)
        assert calculate_baseline_value(baseline, "ratio") == 10

    def test_returns_none_when_no_samples(self):
        baseline = BaselineStats(number_of_samples=0, sum=100)
        assert calculate_baseline_value(baseline, "mean_count") is None

    def test_ratio_returns_none_when_denominator_zero(self):
        baseline = BaselineStats(number_of_samples=1000, sum=100, denominator_sum=0)
        assert calculate_baseline_value(baseline, "ratio") is None


class TestCalculateVariance:
    @parameterized.expand(
        [
            ("mean_count", 4, 8),  # 2 * 4
            ("mean_sum_or_avg", 50, 625),  # 0.25 * 50^2
            ("funnel", 0.1, None),  # embedded in p(1-p)
        ]
    )
    def test_variance_from_baseline_value(self, metric_type, baseline_value, expected):
        assert calculate_variance(metric_type, baseline_value) == expected


class TestCalculateVarianceFromStats:
    def test_ratio_delta_method(self):
        baseline = BaselineStats(
            number_of_samples=10000,
            sum=500000,
            sum_squares=30000000,
            denominator_sum=50000,
            denominator_sum_squares=300000,
            numerator_denominator_sum_product=2600000,
        )
        variance = calculate_variance_from_stats(10, "ratio", baseline)
        assert variance is not None
        assert math.isclose(variance, 32 * 10000 / 9999, rel_tol=1e-6)

    def test_ratio_zero_covariance(self):
        baseline = BaselineStats(
            number_of_samples=1000,
            sum=5000,
            sum_squares=30000,
            denominator_sum=10000,
            denominator_sum_squares=105000,
            numerator_denominator_sum_product=50000,
        )
        variance = calculate_variance_from_stats(0.5, "ratio", baseline)
        assert variance is not None
        assert math.isclose(variance, 0.0625 * 1000 / 999, rel_tol=1e-6)

    def test_ratio_high_positive_covariance_reduces_variance(self):
        baseline = BaselineStats(
            number_of_samples=1000,
            sum=5000,
            sum_squares=30000,
            denominator_sum=10000,
            denominator_sum_squares=105000,
            numerator_denominator_sum_product=52000,
        )
        variance = calculate_variance_from_stats(0.5, "ratio", baseline)
        assert variance is not None
        assert variance < 0.0625

    def test_retention_delta_method(self):
        baseline = BaselineStats(
            number_of_samples=10000,
            sum=7000,
            sum_squares=7000,
            denominator_sum=10000,
            denominator_sum_squares=10000,
            numerator_denominator_sum_product=7000,
        )
        variance = calculate_variance_from_stats(0.7, "retention", baseline)
        assert variance is not None
        assert math.isclose(variance, 0.21 * 10000 / 9999, rel_tol=1e-6)

    @parameterized.expand(
        [
            ("zero_retention", 0, 0, 0, 0),
            ("perfect_retention", 1000, 1000, 1000, 1000),
        ]
    )
    def test_retention_edge_cases_have_zero_variance(self, _name, sum_, sum_squares, product, _denom_unused):
        baseline = BaselineStats(
            number_of_samples=1000,
            sum=sum_,
            sum_squares=sum_squares,
            denominator_sum=1000,
            denominator_sum_squares=1000,
            numerator_denominator_sum_product=product,
        )
        baseline_value = calculate_baseline_value(baseline, "retention")
        assert baseline_value is not None
        variance = calculate_variance_from_stats(baseline_value, "retention", baseline)
        assert variance is not None
        assert math.isclose(variance, 0, abs_tol=1e-9)

    @parameterized.expand(
        [
            ("observed_spread", BaselineStats(number_of_samples=1000, sum=1000, sum_squares=26000), 25000 / 999),
            ("sum_squares_left_out", BaselineStats(number_of_samples=1000, sum=1000), 0.25),
        ]
    )
    def test_mean_variance_follows_the_observed_spread(self, _name, baseline, expected):
        assert math.isclose(calculate_variance_from_stats(1, "mean_sum_or_avg", baseline) or 0, expected)

    def test_returns_none_without_baseline(self):
        assert calculate_variance_from_stats(0.05, "ratio", None) is None

    def test_returns_none_when_samples_zero(self):
        baseline = BaselineStats(number_of_samples=0, sum=100, denominator_sum=1000)
        assert calculate_variance_from_stats(10, "ratio", baseline) is None

    def test_returns_none_without_the_denominators_spread(self):
        baseline = BaselineStats(number_of_samples=1000, sum=5000, sum_squares=30000, denominator_sum=10000)
        assert calculate_variance_from_stats(0.5, "ratio", baseline) is None


class TestCalculateSampleSize:
    @parameterized.expand(
        [
            # metric_type, baseline_value, mde, variants, expected
            ("mean_count", 4, 5, 2, 6400),
            ("mean_sum_or_avg", 50, 5, 2, 3200),
            ("funnel", 0.1, 50, 2, 1152),
        ]
    )
    def test_sample_size(self, metric_type, baseline_value, mde, variants, expected):
        assert calculate_sample_size(metric_type, baseline_value, mde, variants) == expected

    @parameterized.expand(
        [
            ("uneven_split", [80, 20], 1800),
            ("even_split_of_three", [1, 1, 1], 1728),
        ]
    )
    def test_sample_size_powers_the_comparison_with_the_smallest_variant(self, _name, split, expected):
        assert calculate_sample_size("funnel", 0.1, 50, len(split), split=split) == expected

    @parameterized.expand(
        [
            ("effect_that_underflows", lambda: calculate_sample_size("mean_sum_or_avg", 1.0, 1e-160, 2)),
            ("effect_that_overflows", lambda: calculate_sample_size("mean_sum_or_avg", 1.0, 1e160, 2)),
            ("baseline_that_overflows", lambda: calculate_sample_size("mean_sum_or_avg", 1e200, 5, 2)),
            ("variance_that_overflows", lambda: calculate_sample_size("ratio", 10, 10, 2, variance=1e308 * 10)),
            (
                "stats_that_overflow",
                lambda: calculate_variance_from_stats(
                    1e200, "mean_sum_or_avg", BaselineStats(number_of_samples=2, sum=1e200, sum_squares=1e300)
                ),
            ),
            (
                "ratio_that_overflows",
                lambda: calculate_baseline_value(
                    BaselineStats(number_of_samples=10, sum=1e308, denominator_sum=1e-308), "ratio"
                ),
            ),
            ("exposure_rate_that_underflows", lambda: calculate_running_time_days(1000, 1e-320)),
            (
                "detectable_effect_that_overflows",
                lambda: calculate_detectable_effect("mean_count", 1e-320, 10, 10, 1.0),
            ),
        ]
    )
    def test_extreme_inputs_give_no_estimate(self, _name, calculate):
        assert calculate() is None

    def test_sizes_an_even_split_of_any_count_without_a_list_per_variant(self):
        assert calculate_sample_size("funnel", 0.1, 50, 10**12) == pytest.approx(576 * 10**12, rel=1e-9)

    def test_returns_none_for_zero_mde(self):
        assert calculate_sample_size("funnel", 0.1, 0, 2) is None

    def test_returns_none_for_zero_baseline(self):
        assert calculate_sample_size("mean_count", 0, 5, 2) is None

    def test_ratio_requires_variance(self):
        assert calculate_sample_size("ratio", 10, 10, 2) is None
        assert calculate_sample_size("ratio", 10, 10, 2, variance=32) == 1024

    def test_returns_none_for_funnel_baseline_above_one(self):
        # A conversion rate above 1 flips the (1 - p) term negative, so the sample size is negative.
        assert calculate_sample_size("funnel", 1.5, 50, 2) is None

    def test_returns_none_for_negative_variance(self):
        # The delta method can return a negative variance, which yields a negative sample size.
        assert calculate_sample_size("ratio", 10, 10, 2, variance=-32) is None


class TestCalculateDetectableEffect:
    @parameterized.expand(
        [
            ("mean_count", 4, 5),
            ("mean_sum_or_avg", 50, 5),
            ("funnel", 0.1, 50),
            ("funnel", 0.03, 30),
        ]
    )
    def test_inverts_the_sample_size(self, metric_type, baseline_value, mde):
        sample_size = calculate_sample_size(metric_type, baseline_value, mde, 2)
        assert sample_size is not None
        samples_per_variant = sample_size // 2

        detectable = calculate_detectable_effect(metric_type, baseline_value, samples_per_variant, samples_per_variant)

        assert detectable == pytest.approx(mde, rel=0.01)


class TestCalculateRunningTimeDays:
    @parameterized.expand(
        [
            (6400, 100, 64),
            (1000, 300, 4),  # ceil(3.33)
            (None, 100, None),
            (6400, 0, None),
            (6400, None, None),
        ]
    )
    def test_running_time(self, sample_size, exposure_rate, expected):
        assert calculate_running_time_days(sample_size, exposure_rate) == expected
