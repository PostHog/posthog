from unittest import TestCase

from products.experiments.stats.frequentist.method import FrequentistConfig, FrequentistMethod
from products.experiments.stats.shared.enums import DifferenceType
from products.experiments.stats.shared.statistics import ProportionStatistic, RatioStatistic, SampleMeanStatistic


def create_test_result_dict(result):
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


class TestTwoSidedTTest(TestCase):
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
        expected_dict = {
            "expected": 0.63646,
            "ci": [-0.0875, 1.36048],
            "p_value": 0.08487,
            "error_message": None,
            "uplift": {"dist": "normal", "mean": 0.636467, "stddev": 0.094233},
        }

        # Compare the key values
        self.assertAlmostEqual(result_dict["expected"], expected_dict["expected"], places=4)
        self.assertAlmostEqual(result_dict["p_value"], expected_dict["p_value"], places=4)
        self.assertAlmostEqual(result_dict["ci"][0], expected_dict["ci"][0], places=4)
        self.assertAlmostEqual(result_dict["ci"][1], expected_dict["ci"][1], places=4)
        self.assertAlmostEqual(result_dict["uplift"]["mean"], expected_dict["uplift"]["mean"], places=4)
        self.assertAlmostEqual(result_dict["uplift"]["stddev"], expected_dict["uplift"]["stddev"], places=4)

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
        expected_dict = {
            "expected": -0.25925,
            "ci": [-0.49475, -0.02376],
            "p_value": 0.030960,
            "error_message": None,
            "uplift": {"dist": "normal", "mean": -0.25925, "stddev": 0.030650},
        }

        # Compare the key values
        self.assertAlmostEqual(result_dict["expected"], expected_dict["expected"], places=4)
        self.assertAlmostEqual(result_dict["p_value"], expected_dict["p_value"], places=4)
        self.assertAlmostEqual(result_dict["ci"][0], expected_dict["ci"][0], places=4)
        self.assertAlmostEqual(result_dict["ci"][1], expected_dict["ci"][1], places=4)
        self.assertAlmostEqual(result_dict["uplift"]["mean"], expected_dict["uplift"]["mean"], places=4)
        self.assertAlmostEqual(result_dict["uplift"]["stddev"], expected_dict["uplift"]["stddev"], places=4)

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
        expected_dict = {
            "expected": 0.041333,
            "ci": [0.01378609, 0.0689],
            "p_value": 0.0032826,
            "error_message": None,
            "uplift": {"dist": "normal", "mean": 0.0413, "stddev": 0.00358537},
        }

        # Compare the key values
        self.assertAlmostEqual(result_dict["expected"], expected_dict["expected"], places=4)
        self.assertAlmostEqual(result_dict["p_value"], expected_dict["p_value"], places=4)
        self.assertAlmostEqual(result_dict["ci"][0], expected_dict["ci"][0], places=4)
        self.assertAlmostEqual(result_dict["ci"][1], expected_dict["ci"][1], places=4)
        self.assertAlmostEqual(result_dict["uplift"]["mean"], expected_dict["uplift"]["mean"], places=4)
        self.assertAlmostEqual(result_dict["uplift"]["stddev"], expected_dict["uplift"]["stddev"], places=4)
