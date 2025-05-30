import numpy as np
from unittest import TestCase
from products.experiments.stats.frequentist.method import FrequentistConfig, FrequentistMethod
from products.experiments.stats.frequentist.statistics import SampleMeanStatistic, TestType, DifferenceType


def create_test_result_dict(result):
    """Convert TestResult to dictionary similar to gbstats format."""
    return {
        "expected": result.point_estimate,
        "ci": [result.confidence_interval[0], result.confidence_interval[1]],
        "p_value": result.p_value,
        "error_message": None,
        "uplift": {
            "dist": "normal",
            "mean": result.point_estimate,
            "stddev": np.sqrt(result.confidence_interval[1] - result.confidence_interval[0]) ** 2 / (2 * 1.96) ** 2
            if result.confidence_interval[1] != float("inf") and result.confidence_interval[0] != float("-inf")
            else None,
        },
    }


class TestTwoSidedTTest(TestCase):
    def test_two_sided_ttest(self):
        """Test basic two-sided t-test with sample mean statistics."""
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
            "uplift": {"dist": "normal", "mean": 0.70732, "stddev": 0.37879},
        }

        # Compare the key values
        self.assertAlmostEqual(result_dict["expected"], expected_dict["expected"], places=4)
        self.assertAlmostEqual(result_dict["p_value"], expected_dict["p_value"], places=4)
        self.assertAlmostEqual(result_dict["ci"][0], expected_dict["ci"][0], places=4)
        self.assertAlmostEqual(result_dict["ci"][1], expected_dict["ci"][1], places=4)
