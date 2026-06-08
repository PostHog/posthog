import math
from typing import Any, cast

from unittest import TestCase

from parameterized import parameterized

from products.experiments.stats.frequentist.method import FrequentistConfig, FrequentistMethod
from products.experiments.stats.frequentist.tests import SequentialTwoSidedTTest
from products.experiments.stats.frequentist.utils import (
    calculate_variance_pooled,
    sequential_interval_halfwidth,
    sequential_p_value,
    sequential_rho,
)
from products.experiments.stats.shared.enums import DifferenceType
from products.experiments.stats.shared.statistics import (
    ProportionStatistic,
    RatioStatistic,
    SampleMeanStatistic,
    StatisticError,
)


def create_test_result_dict(result: Any) -> dict[str, Any]:
    """Convert TestResult to dictionary for easy interpretation."""
    return {
        "expected": result.point_estimate,
        "ci": [result.confidence_interval[0], result.confidence_interval[1]],
        "p_value": result.p_value,
        "error_message": None,
        "uplift": {
            "dist": "normal",
            "mean": result.point_estimate,
            "stddev": (result.confidence_interval[1] - result.confidence_interval[0]) / (2 * 1.96) ** 2
            if result.confidence_interval[1] != float("inf") and result.confidence_interval[0] != float("-inf")
            else None,
        },
    }


def get_ci(result_dict: dict[str, Any]) -> list[Any]:
    return cast(list[Any], result_dict["ci"])


def get_expected_uplift(expected_dict: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], expected_dict["uplift"])


class TestTwoSidedTTest(TestCase):
    @staticmethod
    def _uplift(result_dict: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], result_dict["uplift"])

    def test_two_sided_ttest_with_sample_mean(self):
        """Test basic two-sided t-test with sample mean statistics."""

        # imported here so that pytest doesn't try to discover tests inside it
        from products.experiments.stats.frequentist.method import TestType

        stat_a = SampleMeanStatistic(sum=1922.7, sum_squares=94698.29, n=2461)
        stat_b = SampleMeanStatistic(sum=1196.87, sum_squares=37377.9767, n=2507)

        config = FrequentistConfig(alpha=0.05, test_type=TestType.TWO_SIDED, difference_type=DifferenceType.RELATIVE)
        method = FrequentistMethod(config)
        result = method.run_test(stat_a, stat_b)

        result_dict = create_test_result_dict(result)
        expected_dict: dict[str, Any] = {
            "expected": 0.63646,
            "ci": [-0.0875, 1.36048],
            "p_value": 0.08487,
            "error_message": None,
            "uplift": {"dist": "normal", "mean": 0.636467, "stddev": 0.094233},
        }

        # Compare the key values
        self.assertAlmostEqual(result_dict["expected"], expected_dict["expected"], places=4)
        self.assertAlmostEqual(result_dict["p_value"], expected_dict["p_value"], places=4)
        ci = get_ci(result_dict)
        self.assertAlmostEqual(ci[0], expected_dict["ci"][0], places=4)
        self.assertAlmostEqual(ci[1], expected_dict["ci"][1], places=4)
        uplift = self._uplift(result_dict)
        expected_uplift = get_expected_uplift(expected_dict)
        self.assertAlmostEqual(uplift["mean"], expected_uplift["mean"], places=4)
        self.assertAlmostEqual(uplift["stddev"], expected_uplift["stddev"], places=4)

    def test_two_sided_ttest_with_sample_proportion(self):
        """Test basic two-sided t-test with sample proportion statistics."""

        # imported here so that pytest doesn't try to discover tests inside it
        from products.experiments.stats.frequentist.method import TestType

        stat_a = ProportionStatistic(sum=62, n=1471)
        stat_b = ProportionStatistic(sum=87, n=1529)

        config = FrequentistConfig(alpha=0.05, test_type=TestType.TWO_SIDED, difference_type=DifferenceType.RELATIVE)
        method = FrequentistMethod(config)
        result = method.run_test(stat_a, stat_b)

        result_dict = create_test_result_dict(result)
        expected_dict: dict[str, Any] = {
            "expected": -0.25925,
            "ci": [-0.49475, -0.02376],
            "p_value": 0.030960,
            "error_message": None,
            "uplift": {"dist": "normal", "mean": -0.25925, "stddev": 0.030650},
        }

        # Compare the key values
        self.assertAlmostEqual(result_dict["expected"], expected_dict["expected"], places=4)
        self.assertAlmostEqual(result_dict["p_value"], expected_dict["p_value"], places=4)
        ci = get_ci(result_dict)
        self.assertAlmostEqual(ci[0], expected_dict["ci"][0], places=4)
        self.assertAlmostEqual(ci[1], expected_dict["ci"][1], places=4)
        uplift = self._uplift(result_dict)
        expected_uplift = get_expected_uplift(expected_dict)
        self.assertAlmostEqual(uplift["mean"], expected_uplift["mean"], places=4)
        self.assertAlmostEqual(uplift["stddev"], expected_uplift["stddev"], places=4)

    def test_two_sided_ttest_with_ratio_statistic(self):
        """Test basic two-sided t-test with ratio statistics."""

        # imported here so that pytest doesn't try to discover tests inside it
        from products.experiments.stats.frequentist.method import TestType

        # treatment
        stat_a_n = 2034
        stat_a = RatioStatistic(
            n=stat_a_n,
            m_statistic=SampleMeanStatistic(n=stat_a_n, sum=99673.9364269569, sum_squares=11298745.182728939),
            d_statistic=SampleMeanStatistic(n=stat_a_n, sum=947, sum_squares=947),
            m_d_sum_of_products=99673.9364269569,
        )
        # control
        stat_b_n = 1966
        stat_b = RatioStatistic(
            n=stat_b_n,
            m_statistic=SampleMeanStatistic(n=stat_b_n, sum=94605.79858780127, sum_squares=10463129.505392816),
            d_statistic=SampleMeanStatistic(n=stat_b_n, sum=936, sum_squares=936),
            m_d_sum_of_products=94605.79858780127,
        )

        config = FrequentistConfig(alpha=0.05, test_type=TestType.TWO_SIDED, difference_type=DifferenceType.RELATIVE)
        method = FrequentistMethod(config)
        result = method.run_test(stat_a, stat_b)

        result_dict = create_test_result_dict(result)
        expected_dict: dict[str, Any] = {
            "expected": 0.041333,
            "ci": [0.01378609, 0.0689],
            "p_value": 0.0032826,
            "error_message": None,
            "uplift": {"dist": "normal", "mean": 0.0413, "stddev": 0.00358537},
        }

        # Compare the key values
        self.assertAlmostEqual(result_dict["expected"], expected_dict["expected"], places=4)
        self.assertAlmostEqual(result_dict["p_value"], expected_dict["p_value"], places=4)
        ci = get_ci(result_dict)
        self.assertAlmostEqual(ci[0], expected_dict["ci"][0], places=4)
        self.assertAlmostEqual(ci[1], expected_dict["ci"][1], places=4)
        uplift = self._uplift(result_dict)
        expected_uplift = get_expected_uplift(expected_dict)
        self.assertAlmostEqual(uplift["mean"], expected_uplift["mean"], places=4)
        self.assertAlmostEqual(uplift["stddev"], expected_uplift["stddev"], places=4)


class TestSequentialMath(TestCase):
    """Unit tests for the sequential testing primitives (rho, half-width, p-value)."""

    def test_sequential_rho_matches_formula(self):
        alpha = 0.05
        n_tuning = 5000.0
        rho = sequential_rho(alpha, n_tuning)
        log_alpha = math.log(alpha)
        expected = math.sqrt((-2 * log_alpha + math.log(-2 * log_alpha + 1)) / n_tuning)
        self.assertAlmostEqual(rho, expected, places=10)

    def test_sequential_rho_rejects_invalid_alpha(self):
        with self.assertRaises(StatisticError):
            sequential_rho(0.0, 5000)
        with self.assertRaises(StatisticError):
            sequential_rho(1.0, 5000)

    def test_sequential_rho_rejects_nonpositive_tuning_parameter(self):
        with self.assertRaises(StatisticError):
            sequential_rho(0.05, 0)
        with self.assertRaises(StatisticError):
            sequential_rho(0.05, -1)

    def test_sequential_halfwidth_wider_than_fixed_horizon(self):
        # Per-observation variance sigma^2 = 1, total n = 5000.
        # Fixed-horizon halfwidth (1.96 * SE) uses SE = sqrt(sigma^2/n).
        s2 = 1.0
        n = 5000
        alpha = 0.05
        seq_halfwidth = sequential_interval_halfwidth(s2, n, 5000, alpha)
        fixed_halfwidth = 1.96 * math.sqrt(s2 / n)
        self.assertGreater(seq_halfwidth, fixed_halfwidth)

    def test_sequential_p_value_clamps_to_one_with_small_n(self):
        # Tiny effect, tiny n: e-value < 1 so p-value clamps to 1.
        p = sequential_p_value(
            point_estimate=0.01,
            pooled_variance=1.0,
            n=10,
            sequential_tuning_parameter=5000,
            alpha=0.05,
        )
        self.assertEqual(p, 1.0)

    def test_sequential_p_value_drops_with_strong_evidence(self):
        # Strong, well-powered effect should produce a small always-valid p-value.
        # SE^2 = 0.0001 (so SE = 0.01) means a 0.5 effect is ~50 standard errors out.
        p_strong = sequential_p_value(
            point_estimate=0.5,
            pooled_variance=0.0001,
            n=10000,
            sequential_tuning_parameter=5000,
            alpha=0.05,
        )
        self.assertLess(p_strong, 0.05)


class TestSequentialTwoSidedTTest(TestCase):
    """End-to-end behavior of SequentialTwoSidedTTest via FrequentistMethod."""

    def test_sequential_ci_is_wider_than_fixed_horizon_ci(self):
        from products.experiments.stats.frequentist.method import TestType

        stat_a = SampleMeanStatistic(sum=1922.7, sum_squares=94698.29, n=2461)
        stat_b = SampleMeanStatistic(sum=1196.87, sum_squares=37377.9767, n=2507)

        config_fixed = FrequentistConfig(
            alpha=0.05, test_type=TestType.TWO_SIDED, difference_type=DifferenceType.RELATIVE
        )
        config_seq = FrequentistConfig(
            alpha=0.05,
            test_type=TestType.TWO_SIDED,
            difference_type=DifferenceType.RELATIVE,
            sequential_testing_enabled=True,
            sequential_tuning_parameter=5000,
        )

        fixed_result = FrequentistMethod(config_fixed).run_test(stat_a, stat_b)
        seq_result = FrequentistMethod(config_seq).run_test(stat_a, stat_b)

        fixed_width = fixed_result.confidence_interval[1] - fixed_result.confidence_interval[0]
        seq_width = seq_result.confidence_interval[1] - seq_result.confidence_interval[0]

        self.assertGreater(seq_width, fixed_width)
        self.assertAlmostEqual(seq_result.point_estimate, fixed_result.point_estimate, places=6)
        self.assertEqual(seq_result.test_type, "sequential_two_sided")
        self.assertTrue(math.isnan(seq_result.degrees_of_freedom))
        self.assertTrue(math.isnan(seq_result.test_statistic))

    def test_sequential_p_value_with_zero_effect_returns_one(self):
        from products.experiments.stats.frequentist.method import TestType

        stat_a = ProportionStatistic(sum=100, n=2000)
        stat_b = ProportionStatistic(sum=100, n=2000)

        config = FrequentistConfig(
            alpha=0.05,
            test_type=TestType.TWO_SIDED,
            difference_type=DifferenceType.ABSOLUTE,
            sequential_testing_enabled=True,
            sequential_tuning_parameter=5000,
        )
        result = FrequentistMethod(config).run_test(stat_a, stat_b)
        self.assertEqual(result.p_value, 1.0)
        self.assertFalse(result.is_significant)

    def test_invalid_tuning_parameter_raises(self):
        with self.assertRaises(StatisticError):
            SequentialTwoSidedTTest(alpha=0.05, sequential_tuning_parameter=0)


class TestSequentialTwoSidedTTestGoldenValues(TestCase):
    """Golden fixtures for the two-sided sequential test.

    The implementation was validated to reproduce the published reference values of
    Waudby-Smith et al. 2023; these fixtures then lock in that behavior on our own
    chosen inputs, guarding the end-to-end computation (point estimate, confidence
    sequence, p-value, and the standard error the CI is built from) against drift.
    run_test takes (treatment, control), so the higher-mean stat is passed first.
    """

    @parameterized.expand(
        [
            (
                "sample_mean_tuning_1000",
                SampleMeanStatistic(sum=2500.0, sum_squares=135000.0, n=3500),
                SampleMeanStatistic(sum=1400.0, sum_squares=52000.0, n=3000),
                1000,
                0.53061,
                (-0.53230, 1.59353),
                0.33368,
                1.0,
            ),
            (
                "proportion_default_tuning",
                ProportionStatistic(sum=2600, n=3500),
                ProportionStatistic(sum=1450, n=3050),
                5000,
                0.56256,
                (0.46064, 0.66448),
                0.03354,
                # Very strong evidence: the e-value is astronomical, so the p-value is a
                # near-zero (~6e-56) that rounds to 0.0 at 5 decimals. The log-space form
                # keeps the accurate tiny value instead of underflowing 1/e-value to 0.
                0.0,
            ),
        ]
    )
    def test_matches_reference_values(self, _name, treatment, control, tuning_parameter, expected, ci, stddev, p_value):
        result = SequentialTwoSidedTTest(alpha=0.05, sequential_tuning_parameter=tuning_parameter).run_test(
            treatment, control, DifferenceType.RELATIVE
        )

        self.assertAlmostEqual(result.point_estimate, expected, places=5)
        self.assertAlmostEqual(result.confidence_interval[0], ci[0], places=5)
        self.assertAlmostEqual(result.confidence_interval[1], ci[1], places=5)
        self.assertAlmostEqual(result.p_value, p_value, places=5)

        # Assert the standard error directly (the SE the sequential CI is built from) so a
        # variance regression is pinpointed, not just inferred from a shifted CI.
        standard_error = math.sqrt(calculate_variance_pooled(treatment, control, DifferenceType.RELATIVE))
        self.assertAlmostEqual(standard_error, stddev, places=5)

    def test_interval_narrowest_near_true_sample_size(self):
        # Same stats as the sample-mean fixture; true total n = 3500 + 3000 = 6500. The
        # confidence sequence is tightest when the tuning parameter ~ true n and widens as
        # it badly under- (10) or over-estimates (10000) it.
        treatment = SampleMeanStatistic(sum=2500.0, sum_squares=135000.0, n=3500)
        control = SampleMeanStatistic(sum=1400.0, sum_squares=52000.0, n=3000)

        def interval(tuning_parameter: float) -> tuple[float, float]:
            test = SequentialTwoSidedTTest(alpha=0.05, sequential_tuning_parameter=tuning_parameter)
            return test.run_test(treatment, control, DifferenceType.RELATIVE).confidence_interval

        below = interval(10)
        near = interval(6500)
        above = interval(10000)

        # Under-estimating the sample size gives the widest interval.
        self.assertLess(below[0], near[0])
        self.assertGreater(below[1], near[1])
        self.assertLess(below[0], above[0])
        self.assertGreater(below[1], above[1])
        # Over-estimating is wider than estimating well, but narrower than under-estimating.
        self.assertLess(above[0], near[0])
        self.assertGreater(above[1], near[1])
