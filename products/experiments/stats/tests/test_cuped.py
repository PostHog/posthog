from unittest import TestCase

import numpy as np
from parameterized import parameterized

from products.experiments.stats.bayesian.method import BayesianConfig, BayesianMethod
from products.experiments.stats.frequentist.method import FrequentistConfig, FrequentistMethod
from products.experiments.stats.shared.cuped import (
    CupedData,
    _adjust_group,
    _compute_covariance,
    compute_theta,
    cuped_adjust,
)
from products.experiments.stats.shared.enums import DifferenceType
from products.experiments.stats.shared.statistics import ProportionStatistic, SampleMeanStatistic, StatisticError


def _generate_sufficient_stats(rng: np.random.Generator, n: int, mean: float, std: float):
    """Generate sufficient statistics (sum, sum_squares) from synthetic data."""
    data = rng.normal(mean, std, n)
    return float(np.sum(data)), float(np.sum(data**2)), data


class TestComputeTheta(TestCase):
    def test_theta_with_known_correlation(self):
        """When Y = 2X + noise, theta should be approximately 2."""
        rng = np.random.default_rng(42)
        n_t, n_c = 1000, 1000

        # Generate pre-exposure data
        pre_t = rng.normal(10, 3, n_t)
        pre_c = rng.normal(10, 3, n_c)

        # Post = 2 * Pre + noise
        post_t = 2 * pre_t + rng.normal(0, 1, n_t)
        post_c = 2 * pre_c + rng.normal(0, 1, n_c)

        treatment_post = SampleMeanStatistic(n=n_t, sum=float(np.sum(post_t)), sum_squares=float(np.sum(post_t**2)))
        control_post = SampleMeanStatistic(n=n_c, sum=float(np.sum(post_c)), sum_squares=float(np.sum(post_c**2)))
        treatment_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=n_t, sum=float(np.sum(pre_t)), sum_squares=float(np.sum(pre_t**2))),
            sum_of_cross_products=float(np.sum(post_t * pre_t)),
        )
        control_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=n_c, sum=float(np.sum(pre_c)), sum_squares=float(np.sum(pre_c**2))),
            sum_of_cross_products=float(np.sum(post_c * pre_c)),
        )

        theta = compute_theta(treatment_post, control_post, treatment_cuped, control_cuped)
        self.assertAlmostEqual(theta, 2.0, places=1)

    def test_theta_zero_when_no_pre_variance(self):
        """When all pre-exposure values are identical, theta should be 0."""
        n = 100
        treatment_post = SampleMeanStatistic(n=n, sum=500.0, sum_squares=3000.0)
        control_post = SampleMeanStatistic(n=n, sum=480.0, sum_squares=2800.0)

        # Constant pre-exposure values: all 5.0
        constant_pre = SampleMeanStatistic(n=n, sum=500.0, sum_squares=2500.0)
        treatment_cuped = CupedData(pre_statistic=constant_pre, sum_of_cross_products=2500.0)
        control_cuped = CupedData(pre_statistic=constant_pre, sum_of_cross_products=2400.0)

        theta = compute_theta(treatment_post, control_post, treatment_cuped, control_cuped)
        self.assertEqual(theta, 0.0)

    def test_theta_with_uncorrelated_data(self):
        """When pre and post are independent, theta should be near 0."""
        rng = np.random.default_rng(123)
        n = 5000

        pre = rng.normal(10, 3, n)
        post = rng.normal(20, 5, n)

        treatment_post = SampleMeanStatistic(n=n, sum=float(np.sum(post)), sum_squares=float(np.sum(post**2)))
        treatment_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=n, sum=float(np.sum(pre)), sum_squares=float(np.sum(pre**2))),
            sum_of_cross_products=float(np.sum(post * pre)),
        )

        # Use same data for control to isolate theta behavior
        theta = compute_theta(treatment_post, treatment_post, treatment_cuped, treatment_cuped)
        self.assertAlmostEqual(theta, 0.0, places=0)


class TestCupedAdjust(TestCase):
    def test_variance_reduction_with_correlated_data(self):
        """CUPED should reduce variance when pre and post are correlated."""
        rng = np.random.default_rng(42)
        n_t, n_c = 1000, 1000

        pre_t = rng.normal(10, 3, n_t)
        pre_c = rng.normal(10, 3, n_c)
        post_t = 2 * pre_t + rng.normal(0.5, 1, n_t)  # treatment has +0.5 effect
        post_c = 2 * pre_c + rng.normal(0, 1, n_c)

        treatment_post = SampleMeanStatistic(n=n_t, sum=float(np.sum(post_t)), sum_squares=float(np.sum(post_t**2)))
        control_post = SampleMeanStatistic(n=n_c, sum=float(np.sum(post_c)), sum_squares=float(np.sum(post_c**2)))
        treatment_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=n_t, sum=float(np.sum(pre_t)), sum_squares=float(np.sum(pre_t**2))),
            sum_of_cross_products=float(np.sum(post_t * pre_t)),
        )
        control_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=n_c, sum=float(np.sum(pre_c)), sum_squares=float(np.sum(pre_c**2))),
            sum_of_cross_products=float(np.sum(post_c * pre_c)),
        )

        result = cuped_adjust(treatment_post, control_post, treatment_cuped, control_cuped)

        # Variance should be significantly reduced
        self.assertGreater(result.variance_reduction_treatment, 0.5)
        self.assertGreater(result.variance_reduction_control, 0.5)

        # Adjusted stats should have lower variance than originals
        self.assertLess(result.treatment_adjusted.variance, treatment_post.variance)
        self.assertLess(result.control_adjusted.variance, control_post.variance)

        # Theta should be approximately 2
        self.assertAlmostEqual(result.theta, 2.0, places=1)

    def test_unadjusted_means_preserved(self):
        """CupedResult should contain the original unadjusted means."""
        rng = np.random.default_rng(42)
        n = 500

        pre = rng.normal(10, 3, n)
        post_t = pre + rng.normal(1, 1, n)
        post_c = pre + rng.normal(0, 1, n)

        treatment_post = SampleMeanStatistic(n=n, sum=float(np.sum(post_t)), sum_squares=float(np.sum(post_t**2)))
        control_post = SampleMeanStatistic(n=n, sum=float(np.sum(post_c)), sum_squares=float(np.sum(post_c**2)))
        treatment_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=n, sum=float(np.sum(pre)), sum_squares=float(np.sum(pre**2))),
            sum_of_cross_products=float(np.sum(post_t * pre)),
        )
        control_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=n, sum=float(np.sum(pre)), sum_squares=float(np.sum(pre**2))),
            sum_of_cross_products=float(np.sum(post_c * pre)),
        )

        result = cuped_adjust(treatment_post, control_post, treatment_cuped, control_cuped)

        self.assertAlmostEqual(result.treatment_unadjusted_mean, treatment_post.mean, places=10)
        self.assertAlmostEqual(result.control_unadjusted_mean, control_post.mean, places=10)

    def test_no_adjustment_when_zero_pre_variance(self):
        """When pre-exposure has zero variance, should return original stats with theta=0."""
        n = 100
        treatment_post = SampleMeanStatistic(n=n, sum=500.0, sum_squares=3000.0)
        control_post = SampleMeanStatistic(n=n, sum=480.0, sum_squares=2800.0)

        constant_pre = SampleMeanStatistic(n=n, sum=500.0, sum_squares=2500.0)
        treatment_cuped = CupedData(pre_statistic=constant_pre, sum_of_cross_products=2500.0)
        control_cuped = CupedData(pre_statistic=constant_pre, sum_of_cross_products=2400.0)

        result = cuped_adjust(treatment_post, control_post, treatment_cuped, control_cuped)

        self.assertEqual(result.theta, 0.0)
        self.assertEqual(result.variance_reduction_treatment, 0.0)
        self.assertEqual(result.variance_reduction_control, 0.0)
        self.assertAlmostEqual(result.treatment_adjusted.mean, treatment_post.mean, places=10)
        self.assertAlmostEqual(result.control_adjusted.mean, control_post.mean, places=10)

    def test_proportion_input_produces_sample_mean_output(self):
        """ProportionStatistic inputs should produce SampleMeanStatistic outputs."""
        n = 1000
        treatment_post = ProportionStatistic(n=n, sum=150)
        control_post = ProportionStatistic(n=n, sum=120)

        rng = np.random.default_rng(42)
        pre_t = rng.normal(0.15, 0.05, n)
        pre_c = rng.normal(0.12, 0.05, n)

        # Generate correlated cross products
        treatment_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=n, sum=float(np.sum(pre_t)), sum_squares=float(np.sum(pre_t**2))),
            sum_of_cross_products=float(np.sum(rng.binomial(1, 0.15, n) * pre_t)),
        )
        control_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=n, sum=float(np.sum(pre_c)), sum_squares=float(np.sum(pre_c**2))),
            sum_of_cross_products=float(np.sum(rng.binomial(1, 0.12, n) * pre_c)),
        )

        result = cuped_adjust(treatment_post, control_post, treatment_cuped, control_cuped)

        self.assertIsInstance(result.treatment_adjusted, SampleMeanStatistic)
        self.assertIsInstance(result.control_adjusted, SampleMeanStatistic)

    @parameterized.expand(
        [
            ("high_correlation", 0.95, 0.8),
            ("medium_correlation", 0.5, 0.05),
        ]
    )
    def test_variance_reduction_scales_with_correlation(self, _name, correlation, min_reduction):
        """Higher correlation between pre and post should give more variance reduction."""
        rng = np.random.default_rng(42)
        n = 2000

        pre = rng.normal(10, 3, n)
        noise_std = 3 * np.sqrt(1 - correlation**2) / correlation if correlation > 0 else 100
        post = correlation * (3 / 3) * pre + rng.normal(0, noise_std, n)

        stat_post = SampleMeanStatistic(n=n, sum=float(np.sum(post)), sum_squares=float(np.sum(post**2)))
        cuped_data = CupedData(
            pre_statistic=SampleMeanStatistic(n=n, sum=float(np.sum(pre)), sum_squares=float(np.sum(pre**2))),
            sum_of_cross_products=float(np.sum(post * pre)),
        )

        result = cuped_adjust(stat_post, stat_post, cuped_data, cuped_data)
        self.assertGreater(result.variance_reduction_treatment, min_reduction)


class TestCupedEdgeCases(TestCase):
    def test_mismatched_n_raises_error(self):
        treatment_post = SampleMeanStatistic(n=100, sum=500.0, sum_squares=3000.0)
        control_post = SampleMeanStatistic(n=100, sum=480.0, sum_squares=2800.0)

        treatment_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=99, sum=490.0, sum_squares=2500.0),  # wrong n
            sum_of_cross_products=2450.0,
        )
        control_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=100, sum=480.0, sum_squares=2400.0),
            sum_of_cross_products=2300.0,
        )

        with self.assertRaises(StatisticError, msg="Treatment post n"):
            cuped_adjust(treatment_post, control_post, treatment_cuped, control_cuped)

    def test_mismatched_types_raises_error(self):
        treatment_post = SampleMeanStatistic(n=100, sum=500.0, sum_squares=3000.0)
        control_post = ProportionStatistic(n=100, sum=50)

        cuped_data = CupedData(
            pre_statistic=SampleMeanStatistic(n=100, sum=480.0, sum_squares=2400.0),
            sum_of_cross_products=2300.0,
        )

        with self.assertRaises(StatisticError, msg="same type"):
            cuped_adjust(treatment_post, control_post, cuped_data, cuped_data)

    def test_small_sample_size(self):
        """CUPED should work (without crashing) even with small samples."""
        n = 5
        rng = np.random.default_rng(42)
        pre = rng.normal(10, 3, n)
        post = pre + rng.normal(1, 1, n)

        stat_post = SampleMeanStatistic(n=n, sum=float(np.sum(post)), sum_squares=float(np.sum(post**2)))
        cuped_data = CupedData(
            pre_statistic=SampleMeanStatistic(n=n, sum=float(np.sum(pre)), sum_squares=float(np.sum(pre**2))),
            sum_of_cross_products=float(np.sum(post * pre)),
        )

        result = cuped_adjust(stat_post, stat_post, cuped_data, cuped_data)
        self.assertIsNotNone(result.theta)
        self.assertIsInstance(result.treatment_adjusted, SampleMeanStatistic)


class TestCupedIntegration(TestCase):
    """End-to-end tests: CUPED adjust → statistical test."""

    def _make_correlated_data(self, rng, n, pre_mean, effect, noise_std):
        pre = rng.normal(pre_mean, 3, n)
        post = pre + rng.normal(effect, noise_std, n)
        post_stat = SampleMeanStatistic(n=n, sum=float(np.sum(post)), sum_squares=float(np.sum(post**2)))
        cuped_data = CupedData(
            pre_statistic=SampleMeanStatistic(n=n, sum=float(np.sum(pre)), sum_squares=float(np.sum(pre**2))),
            sum_of_cross_products=float(np.sum(post * pre)),
        )
        return post_stat, cuped_data

    def test_frequentist_cuped_narrows_confidence_interval(self):
        """CUPED-adjusted stats should produce tighter CIs than unadjusted."""
        rng = np.random.default_rng(42)

        treatment_post, treatment_cuped = self._make_correlated_data(rng, 1000, 10, 0.5, 1)
        control_post, control_cuped = self._make_correlated_data(rng, 1000, 10, 0, 1)

        # Unadjusted
        method = FrequentistMethod(FrequentistConfig(difference_type=DifferenceType.ABSOLUTE))
        unadjusted_result = method.run_test(treatment_post, control_post)

        # CUPED-adjusted
        cuped_result = cuped_adjust(treatment_post, control_post, treatment_cuped, control_cuped)
        adjusted_result = method.run_test(cuped_result.treatment_adjusted, cuped_result.control_adjusted)

        unadjusted_width = unadjusted_result.confidence_interval[1] - unadjusted_result.confidence_interval[0]
        adjusted_width = adjusted_result.confidence_interval[1] - adjusted_result.confidence_interval[0]

        self.assertLess(adjusted_width, unadjusted_width)

    def test_bayesian_cuped_narrows_credible_interval(self):
        """CUPED-adjusted stats should produce tighter credible intervals than unadjusted."""
        rng = np.random.default_rng(42)

        treatment_post, treatment_cuped = self._make_correlated_data(rng, 1000, 10, 0.5, 1)
        control_post, control_cuped = self._make_correlated_data(rng, 1000, 10, 0, 1)

        method = BayesianMethod(BayesianConfig(difference_type=DifferenceType.ABSOLUTE))

        # Unadjusted
        unadjusted_result = method.run_test(treatment_post, control_post)

        # CUPED-adjusted
        cuped_result = cuped_adjust(treatment_post, control_post, treatment_cuped, control_cuped)
        adjusted_result = method.run_test(cuped_result.treatment_adjusted, cuped_result.control_adjusted)

        unadjusted_width = unadjusted_result.credible_interval[1] - unadjusted_result.credible_interval[0]
        adjusted_width = adjusted_result.credible_interval[1] - adjusted_result.credible_interval[0]

        self.assertLess(adjusted_width, unadjusted_width)

    def test_frequentist_cuped_produces_valid_result(self):
        """CUPED-adjusted results should be structurally valid."""
        rng = np.random.default_rng(42)

        treatment_post, treatment_cuped = self._make_correlated_data(rng, 500, 10, 1, 2)
        control_post, control_cuped = self._make_correlated_data(rng, 500, 10, 0, 2)

        cuped_result = cuped_adjust(treatment_post, control_post, treatment_cuped, control_cuped)

        method = FrequentistMethod(FrequentistConfig(difference_type=DifferenceType.ABSOLUTE))
        result = method.run_test(cuped_result.treatment_adjusted, cuped_result.control_adjusted)

        self.assertIsNotNone(result.p_value)
        self.assertGreaterEqual(result.p_value, 0)
        self.assertLessEqual(result.p_value, 1)
        self.assertLess(result.confidence_interval[0], result.confidence_interval[1])

    def test_bayesian_cuped_produces_valid_result(self):
        """CUPED-adjusted results should be structurally valid for Bayesian method."""
        rng = np.random.default_rng(42)

        treatment_post, treatment_cuped = self._make_correlated_data(rng, 500, 10, 1, 2)
        control_post, control_cuped = self._make_correlated_data(rng, 500, 10, 0, 2)

        cuped_result = cuped_adjust(treatment_post, control_post, treatment_cuped, control_cuped)

        method = BayesianMethod(BayesianConfig(difference_type=DifferenceType.ABSOLUTE))
        result = method.run_test(cuped_result.treatment_adjusted, cuped_result.control_adjusted)

        self.assertIsNotNone(result.chance_to_win)
        self.assertGreaterEqual(result.chance_to_win, 0)
        self.assertLessEqual(result.chance_to_win, 1)
        self.assertLess(result.credible_interval[0], result.credible_interval[1])


class TestCupedReferenceData(TestCase):
    """Tests verifying CUPED math against known expected values.

    These tests use deterministic inputs with pre-computed expected outputs
    to verify theta computation, per-group adjustment, covariance, and
    end-to-end frequentist analysis.
    """

    # --- Per-group adjustment with known theta ---

    def test_adjust_group_theta_zero(self):
        """theta=0 gives unadjusted mean and variance."""
        post = SampleMeanStatistic(n=5, sum=14, sum_squares=48)
        cuped_data = CupedData(
            pre_statistic=SampleMeanStatistic(n=5, sum=28.5, sum_squares=520.3),
            sum_of_cross_products=85.2,
        )
        adjusted, vr = _adjust_group(post, cuped_data, theta=0)

        self.assertAlmostEqual(adjusted.mean, 2.8, places=9)
        self.assertAlmostEqual(adjusted.variance, 2.2, places=9)
        self.assertAlmostEqual(vr, 0.0, places=9)

    def test_adjust_group_nonzero_theta(self):
        """Nonzero theta adjusts mean and variance."""
        post = SampleMeanStatistic(n=5, sum=14, sum_squares=48)
        cuped_data = CupedData(
            pre_statistic=SampleMeanStatistic(n=5, sum=28.5, sum_squares=520.3),
            sum_of_cross_products=85.2,
        )
        adjusted, _ = _adjust_group(post, cuped_data, theta=0.31)

        self.assertAlmostEqual(adjusted.mean, 1.033, places=5)
        self.assertAlmostEqual(adjusted.variance, 9.960346, places=4)

    def test_covariance_computation(self):
        """Sample covariance: (85.2 - 14*28.5/5) / 4 = 1.35."""
        cov = _compute_covariance(n=5, post_sum=14, pre_sum=28.5, sum_of_cross_products=85.2)
        self.assertAlmostEqual(cov, 1.35, places=9)

    def test_adjust_group_single_observation(self):
        """n=1 gives variance=0 regardless of theta."""
        post = SampleMeanStatistic(n=1, sum=8.0, sum_squares=64.0)
        cuped_data = CupedData(
            pre_statistic=SampleMeanStatistic(n=1, sum=15.3, sum_squares=15.3**2),
            sum_of_cross_products=50.0,
        )
        adjusted, _ = _adjust_group(post, cuped_data, theta=0.4)

        self.assertAlmostEqual(adjusted.variance, 0.0, places=9)

    # --- Theta computation ---

    def test_theta_pooled_identical_groups(self):
        """Theta from pooling identical control and treatment."""
        post = SampleMeanStatistic(n=5, sum=14, sum_squares=48)
        cuped_data = CupedData(
            pre_statistic=SampleMeanStatistic(n=5, sum=28.5, sum_squares=520.3),
            sum_of_cross_products=85.2,
        )

        theta = compute_theta(post, post, cuped_data, cuped_data)

        self.assertAlmostEqual(theta, 0.015090122, places=7)

    # --- End-to-end mean metric, frequentist ---

    def test_mean_metric_theta_and_adjusted_stats(self):
        """Verify theta, adjusted means, and adjusted variances for mean metric."""
        control_post = SampleMeanStatistic(n=2801, sum=280, sum_squares=560)
        treatment_post = SampleMeanStatistic(n=2800, sum=205, sum_squares=510)
        control_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=2801, sum=195, sum_squares=390),
            sum_of_cross_products=-18,
        )
        treatment_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=2800, sum=110, sum_squares=380),
            sum_of_cross_products=-8,
        )

        result = cuped_adjust(treatment_post, control_post, treatment_cuped, control_cuped)

        self.assertAlmostEqual(result.control_unadjusted_mean, 0.099964299, places=7)
        self.assertAlmostEqual(result.treatment_unadjusted_mean, 0.073214286, places=7)
        self.assertAlmostEqual(result.theta, -0.069566052, places=7)
        self.assertAlmostEqual(result.control_adjusted.mean, 0.104807347, places=7)
        self.assertAlmostEqual(result.treatment_adjusted.mean, 0.075947238, places=7)
        self.assertLess(result.control_adjusted.variance, control_post.variance)
        self.assertLess(result.treatment_adjusted.variance, treatment_post.variance)

    def test_mean_metric_relative_effect(self):
        """Verify relative effect for mean metric with unadjusted_mean override."""
        control_post = SampleMeanStatistic(n=2801, sum=280, sum_squares=560)
        treatment_post = SampleMeanStatistic(n=2800, sum=205, sum_squares=510)
        control_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=2801, sum=195, sum_squares=390),
            sum_of_cross_products=-18,
        )
        treatment_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=2800, sum=110, sum_squares=380),
            sum_of_cross_products=-8,
        )

        result = cuped_adjust(treatment_post, control_post, treatment_cuped, control_cuped)

        # Pass unadjusted control mean as unadjusted_mean for correct CUPED relative effect
        method = FrequentistMethod(FrequentistConfig(difference_type=DifferenceType.RELATIVE))
        test_result = method.run_test(
            result.treatment_adjusted, result.control_adjusted, unadjusted_mean=result.control_unadjusted_mean
        )

        self.assertAlmostEqual(test_result.point_estimate, -0.288704169, places=5)
        self.assertAlmostEqual(test_result.confidence_interval[0], -0.486775, places=5)
        self.assertAlmostEqual(test_result.confidence_interval[1], -0.090633, places=5)
        self.assertTrue(test_result.is_significant)

    def test_mean_metric_relative_effect_bayesian(self):
        """Verify unadjusted_mean works with Bayesian method too."""
        control_post = SampleMeanStatistic(n=2801, sum=280, sum_squares=560)
        treatment_post = SampleMeanStatistic(n=2800, sum=205, sum_squares=510)
        control_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=2801, sum=195, sum_squares=390),
            sum_of_cross_products=-18,
        )
        treatment_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=2800, sum=110, sum_squares=380),
            sum_of_cross_products=-8,
        )

        result = cuped_adjust(treatment_post, control_post, treatment_cuped, control_cuped)

        method = BayesianMethod(BayesianConfig(difference_type=DifferenceType.RELATIVE))
        test_result = method.run_test(
            result.treatment_adjusted, result.control_adjusted, unadjusted_mean=result.control_unadjusted_mean
        )

        self.assertAlmostEqual(test_result.effect_size, -0.288704169, places=4)
        self.assertAlmostEqual(test_result.credible_interval[0], -0.486732, places=5)
        self.assertAlmostEqual(test_result.credible_interval[1], -0.090676, places=5)

    # --- Binomial metric ---

    def test_binomial_metric(self):
        """Binomial metric with CUPED: ProportionStatistic post, binary pre (ss=sum)."""
        control_post = ProportionStatistic(n=2801, sum=280)
        treatment_post = ProportionStatistic(n=2800, sum=205)
        control_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=2801, sum=195, sum_squares=195),
            sum_of_cross_products=-18,
        )
        treatment_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=2800, sum=110, sum_squares=110),
            sum_of_cross_products=-8,
        )

        result = cuped_adjust(treatment_post, control_post, treatment_cuped, control_cuped)

        self.assertIsInstance(result.treatment_adjusted, SampleMeanStatistic)
        self.assertIsInstance(result.control_adjusted, SampleMeanStatistic)
        self.assertAlmostEqual(result.control_unadjusted_mean, 280 / 2801, places=9)
        self.assertAlmostEqual(result.treatment_unadjusted_mean, 205 / 2800, places=9)
        self.assertGreater(result.variance_reduction_treatment, 0)
        self.assertGreater(result.variance_reduction_control, 0)

        method = FrequentistMethod(FrequentistConfig(difference_type=DifferenceType.RELATIVE))
        test_result = method.run_test(
            result.treatment_adjusted, result.control_adjusted, unadjusted_mean=result.control_unadjusted_mean
        )
        self.assertTrue(test_result.is_significant)
        self.assertLess(test_result.point_estimate, 0)

    # --- 3-armed test adjusted standard deviations ---

    @parameterized.expand(
        [
            (
                "control_with_theta_from_treatment2",
                SampleMeanStatistic(n=2801, sum=280, sum_squares=560),
                CupedData(
                    pre_statistic=SampleMeanStatistic(n=2801, sum=195, sum_squares=390), sum_of_cross_products=-18
                ),
                # theta computed from control + treatment2
                SampleMeanStatistic(n=3500, sum=420, sum_squares=840),
                CupedData(
                    pre_statistic=SampleMeanStatistic(n=3500, sum=280, sum_squares=560), sum_of_cross_products=-25
                ),
                0.434365539,
            ),
            (
                "treatment1_with_theta_from_treatment1",
                SampleMeanStatistic(n=2800, sum=205, sum_squares=510),
                CupedData(
                    pre_statistic=SampleMeanStatistic(n=2800, sum=110, sum_squares=380), sum_of_cross_products=-8
                ),
                # theta computed from control + treatment1
                SampleMeanStatistic(n=2800, sum=205, sum_squares=510),
                CupedData(
                    pre_statistic=SampleMeanStatistic(n=2800, sum=110, sum_squares=380), sum_of_cross_products=-8
                ),
                0.420353709,
            ),
            (
                "treatment2_with_theta_from_treatment2",
                SampleMeanStatistic(n=3500, sum=420, sum_squares=840),
                CupedData(
                    pre_statistic=SampleMeanStatistic(n=3500, sum=280, sum_squares=560), sum_of_cross_products=-25
                ),
                # theta computed from control + treatment2
                SampleMeanStatistic(n=3500, sum=420, sum_squares=840),
                CupedData(
                    pre_statistic=SampleMeanStatistic(n=3500, sum=280, sum_squares=560), sum_of_cross_products=-25
                ),
                0.473119119,
            ),
        ]
    )
    def test_three_armed_adjusted_stddev(
        self,
        _name,
        target_post,
        target_cuped,
        theta_partner_post,
        theta_partner_cuped,
        expected_stddev,
    ):
        """Verify per-group adjusted standard deviations in a 3-armed test.

        Each treatment's theta is computed from its pair with control.
        The control's stats use the last treatment pair's theta.
        """
        control_post = SampleMeanStatistic(n=2801, sum=280, sum_squares=560)
        control_cuped = CupedData(
            pre_statistic=SampleMeanStatistic(n=2801, sum=195, sum_squares=390),
            sum_of_cross_products=-18,
        )

        theta = compute_theta(theta_partner_post, control_post, theta_partner_cuped, control_cuped)
        adjusted, _ = _adjust_group(target_post, target_cuped, theta)

        self.assertAlmostEqual(np.sqrt(adjusted.variance), expected_stddev, places=5)
