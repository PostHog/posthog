import math

from parameterized import parameterized

from products.experiments.backend.running_time_calculator import (
    BaselineStats,
    calculate_baseline_value,
    calculate_recommended_sample_size,
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
        assert math.isclose(variance, 32, rel_tol=1e-6)

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
        assert math.isclose(variance, 0.0625, rel_tol=1e-6)

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
        assert math.isclose(variance, 0.21, rel_tol=1e-6)

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

    def test_returns_none_without_baseline(self):
        assert calculate_variance_from_stats(0.05, "ratio", None) is None

    def test_returns_none_when_samples_zero(self):
        baseline = BaselineStats(number_of_samples=0, sum=100, denominator_sum=1000)
        assert calculate_variance_from_stats(10, "ratio", baseline) is None

    def test_handles_missing_optional_fields(self):
        baseline = BaselineStats(number_of_samples=1000, sum=5000, sum_squares=30000, denominator_sum=10000)
        variance = calculate_variance_from_stats(0.5, "ratio", baseline)
        assert variance is not None


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

    def test_returns_none_for_zero_mde(self):
        assert calculate_sample_size("funnel", 0.1, 0, 2) is None

    def test_returns_none_for_zero_baseline(self):
        assert calculate_sample_size("mean_count", 0, 5, 2) is None

    def test_ratio_requires_variance(self):
        assert calculate_sample_size("ratio", 10, 10, 2) is None
        assert calculate_sample_size("ratio", 10, 10, 2, variance=32) == 1024


class TestCalculateRecommendedSampleSize:
    @parameterized.expand(
        [
            ("mean_count", 4, 5, 2, None, 6400),
            ("mean_sum_or_avg", 50, 5, 2, None, 3200),
            ("funnel", 0.1, 50, 2, None, 1152),
        ]
    )
    def test_simple_metrics(self, metric_type, baseline_value, mde, variants, baseline, expected):
        assert calculate_recommended_sample_size(metric_type, mde, baseline_value, variants, baseline) == expected

    def test_ratio(self):
        baseline = BaselineStats(
            number_of_samples=10000,
            sum=500000,
            sum_squares=30000000,
            denominator_sum=50000,
            denominator_sum_squares=300000,
            numerator_denominator_sum_product=2600000,
        )
        assert calculate_recommended_sample_size("ratio", 10, 10, 2, baseline) == 1024

    def test_retention(self):
        baseline = BaselineStats(
            number_of_samples=10000,
            sum=7000,
            sum_squares=7000,
            denominator_sum=10000,
            denominator_sum_squares=10000,
            numerator_denominator_sum_product=7000,
        )
        assert calculate_recommended_sample_size("retention", 10, 0.7, 2, baseline) == 1372


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
