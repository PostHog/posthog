"""
Shared statistical utilities for A/B testing.

This module provides fundamental statistical utilities that are used
by both frequentist and Bayesian methods.
"""

from .statistics import (
    SampleMeanStatistic,
    ProportionStatistic,
    AnyStatistic,
    StatisticError,
)


def get_mean(statistic: AnyStatistic) -> float:
    """Extract the mean/central value from any statistic type."""
    if isinstance(statistic, SampleMeanStatistic):
        return statistic.mean
    elif isinstance(statistic, ProportionStatistic):
        return statistic.proportion
    else:
        raise StatisticError(f"Unknown statistic type: {type(statistic)}")


def get_variance(statistic: AnyStatistic) -> float:
    """Extract the variance from any statistic type."""
    return statistic.variance


def get_sample_size(statistic: AnyStatistic) -> int:
    """Extract the sample size from any statistic type."""
    return statistic.n
