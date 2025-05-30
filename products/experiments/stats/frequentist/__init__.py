"""
Frequentist statistical methods for A/B testing.

This package implements classical hypothesis testing using Welch's t-test
for unequal variances, with support for various statistic types and
sequential testing methods.
"""

# Main API exports
from .method import FrequentistMethod, FrequentistConfig
from .enums import TestType
from .statistics import (
    SampleMeanStatistic,
    ProportionStatistic,
    RatioStatistic,
    RegressionAdjustedStatistic,
    QuantileStatistic,
    StatisticError,
    InvalidStatisticError,
)
from .enums import DifferenceType
from .tests import TestResult

# Version
__version__ = "0.1.0"


# Convenience factory functions
def create_sample_mean_statistic(n: int, sum: float, sum_squares: float) -> SampleMeanStatistic:
    """Create a SampleMeanStatistic with validation."""
    return SampleMeanStatistic(n=n, sum=sum, sum_squares=sum_squares)


def create_proportion_statistic(n: int, successes: int) -> ProportionStatistic:
    """Create a ProportionStatistic with validation."""
    return ProportionStatistic(n=n, sum=successes)


def create_simple_test(
    alpha: float = 0.05, test_type: str = "two_sided", difference_type: str = "relative"
) -> FrequentistMethod:
    """Create a simple FrequentistMethod with string parameters."""
    config = FrequentistMethod.create_simple_config(alpha, test_type, difference_type)
    return FrequentistMethod(config)


__all__ = [
    "FrequentistMethod",
    "FrequentistConfig",
    "TestType",
    "TestResult",
    "SampleMeanStatistic",
    "ProportionStatistic",
    "RatioStatistic",
    "RegressionAdjustedStatistic",
    "QuantileStatistic",
    "DifferenceType",
    "StatisticError",
    "InvalidStatisticError",
    "create_sample_mean_statistic",
    "create_proportion_statistic",
    "create_simple_test",
]
