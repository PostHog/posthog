"""
Shared statistical utilities for A/B testing.

This module provides fundamental statistical utilities that are used
by both frequentist and Bayesian methods.
"""

import numpy as np

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


def validate_statistic_inputs(statistic: AnyStatistic) -> list[str]:
    """
    Comprehensive validation of a statistic object.

    Args:
        statistic: Any statistic object to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    try:
        n = get_sample_size(statistic)
        mean = get_mean(statistic)
        variance = get_variance(statistic)

        # Check for basic validity
        if n <= 0:
            errors.append("Sample size must be positive")

        if not np.isfinite(mean):
            errors.append("Mean must be finite")

        if not np.isfinite(variance) or variance < 0:
            errors.append("Variance must be finite and non-negative")

        # Type-specific validation
        if isinstance(statistic, SampleMeanStatistic):
            errors.extend(_validate_sample_mean(statistic))
        elif isinstance(statistic, ProportionStatistic):
            errors.extend(_validate_proportion(statistic))

    except Exception as e:
        errors.append(f"Failed to validate statistic: {str(e)}")

    return errors


def _validate_sample_mean(stat: SampleMeanStatistic) -> list[str]:
    """Validate SampleMeanStatistic."""
    errors = []

    # Check sum_squares constraint
    if stat.n > 1:
        min_sum_squares = stat.sum**2 / stat.n
        if stat.sum_squares < min_sum_squares - 1e-10:  # Small tolerance for floating point
            errors.append("sum_squares violates mathematical constraint")

    # Check for extreme values
    if abs(stat.sum) > 1e15:
        errors.append("Sum value extremely large - potential overflow risk")

    if stat.sum_squares > 1e30:
        errors.append("Sum of squares extremely large - potential overflow risk")

    return errors


def _validate_proportion(stat: ProportionStatistic) -> list[str]:
    """Validate ProportionStatistic."""
    errors = []

    # Check that sum <= n
    if stat.sum > stat.n:
        errors.append("Number of successes cannot exceed sample size")

    if stat.sum < 0:
        errors.append("Number of successes cannot be negative")

    # Check for extreme proportions
    p = stat.proportion
    if p < 1e-10 or p > 1 - 1e-10:
        errors.append("Proportion extremely close to 0 or 1 - statistical tests may be unreliable")

    return errors


def check_sample_size_adequacy(treatment_stat: AnyStatistic, control_stat: AnyStatistic, min_size: int = 30) -> None:
    """
    Check if sample sizes are adequate for statistical testing.

    Args:
        treatment_stat: Treatment group statistic
        control_stat: Control group statistic
        min_size: Minimum required sample size

    Raises:
        StatisticError: If sample sizes are too small
    """
    treatment_n = get_sample_size(treatment_stat)
    control_n = get_sample_size(control_stat)

    if treatment_n < min_size:
        raise StatisticError(f"Treatment sample size ({treatment_n}) below minimum ({min_size})")

    if control_n < min_size:
        raise StatisticError(f"Control sample size ({control_n}) below minimum ({min_size})")


def validate_test_inputs(
    treatment_stat: AnyStatistic, control_stat: AnyStatistic, check_sample_size: bool = False
) -> None:
    """
    Comprehensive validation of test inputs.

    Args:
        treatment_stat: Treatment group statistic
        control_stat: Control group statistic
        check_sample_size: Whether to enforce minimum sample size requirements

    Raises:
        StatisticError: If validation fails
    """
    # Validate individual statistics
    treatment_errors = validate_statistic_inputs(treatment_stat)
    if treatment_errors:
        raise StatisticError(f"Treatment statistic validation failed: {'; '.join(treatment_errors)}")

    control_errors = validate_statistic_inputs(control_stat)
    if control_errors:
        raise StatisticError(f"Control statistic validation failed: {'; '.join(control_errors)}")

    # Check compatibility
    if type(treatment_stat) is not type(control_stat):
        raise StatisticError("Treatment and control statistics must be the same type")

    # Additional checks (optional for different methods)
    if check_sample_size:
        check_sample_size_adequacy(treatment_stat, control_stat)
