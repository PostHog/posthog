"""
Shared statistical utilities for A/B testing.

This module provides fundamental statistical utilities that are used
by both frequentist and Bayesian methods.
"""

import numpy as np

from .statistics import (
    AnyStatistic,
    ProportionStatistic,
    QuantileStatistic,
    RatioStatistic,
    RelativeEffectBaseline,
    SampleMeanStatistic,
    StatisticError,
)


def get_mean(statistic: AnyStatistic) -> float:
    """Extract the mean/central value from any statistic type."""
    if isinstance(statistic, SampleMeanStatistic):
        return statistic.mean
    elif isinstance(statistic, ProportionStatistic):
        return statistic.proportion
    elif isinstance(statistic, RatioStatistic):
        return statistic.ratio
    elif isinstance(statistic, QuantileStatistic):
        return statistic.mean
    else:
        raise StatisticError(f"Unknown statistic type: {type(statistic)}")


def get_variance(statistic: AnyStatistic) -> float:
    """Extract the variance from any statistic type."""
    return statistic.variance


def get_sample_size(statistic: AnyStatistic) -> int:
    """Extract the sample size from any statistic type."""
    return statistic.n


def variance_of_ratios(
    mean_numerator: float, var_numerator: float, mean_denominator: float, var_denominator: float, covariance: float
) -> float:
    """
    Calculate variance of ratio using delta method.

    For ratio R = M/D, the variance is approximately:
    Var(R) ≈ Var(M)/D² + M²Var(D)/D⁴ - 2M*Cov(M,D)/D³

    Args:
        mean_numerator: Mean of numerator
        var_numerator: Variance of numerator
        mean_denominator: Mean of denominator
        var_denominator: Variance of denominator
        covariance: Covariance between numerator and denominator

    Returns:
        Variance of the ratio
    """
    if abs(mean_denominator) < 1e-10:
        raise StatisticError("Denominator mean cannot be zero for ratio variance calculation")

    return (
        var_numerator / mean_denominator**2
        + mean_numerator**2 * var_denominator / mean_denominator**4
        - 2 * mean_numerator * covariance / mean_denominator**3
    )


def _resolve_relative_effect_baseline(
    control_stat: AnyStatistic, relative_effect_baseline: RelativeEffectBaseline | None
) -> RelativeEffectBaseline:
    if relative_effect_baseline is None:
        control_mean_variance = get_variance(control_stat) / get_sample_size(control_stat)
        # Without CUPED the difference subtracts the baseline itself, so their covariance is minus its variance.
        relative_effect_baseline = RelativeEffectBaseline(
            mean=get_mean(control_stat),
            variance=control_mean_variance,
            difference_covariance=-control_mean_variance,
        )
    if abs(relative_effect_baseline.mean) < 1e-10:
        raise StatisticError("Baseline mean is zero, so the relative difference is undefined")
    return relative_effect_baseline


def relative_effect(
    treatment_stat: AnyStatistic,
    control_stat: AnyStatistic,
    relative_effect_baseline: RelativeEffectBaseline | None = None,
) -> float:
    """
    The treatment-control difference divided by the magnitude of the baseline mean, so that the sign of the
    effect follows the means. The baseline is the control statistic unless CUPED supplies the raw control moments.
    """
    baseline = _resolve_relative_effect_baseline(control_stat, relative_effect_baseline)
    return (get_mean(treatment_stat) - get_mean(control_stat)) / abs(baseline.mean)


def relative_effect_variance(
    treatment_stat: AnyStatistic,
    control_stat: AnyStatistic,
    relative_effect_baseline: RelativeEffectBaseline | None = None,
) -> float:
    """Delta-method variance of `relative_effect`."""
    baseline = _resolve_relative_effect_baseline(control_stat, relative_effect_baseline)
    control_mean_variance = get_variance(control_stat) / get_sample_size(control_stat)
    # The effect is ±D/B for the difference D = T - C and the baseline B, so it has the variance of D/B, and the
    # covariance term keeps the signed B. Write D/B as (T + S)/B - 1, where S = B - C is the shift that CUPED applies
    # to the control mean. Without CUPED, S and its moments are exactly zero. So a treatment arm with no spread and a
    # zero mean gets a variance of exactly zero, which both methods reject, instead of a rounding residue of opposite
    # terms that can be a tiny positive value and read as decisive.
    return variance_of_ratios(
        mean_numerator=get_mean(treatment_stat) + (baseline.mean - get_mean(control_stat)),
        var_numerator=get_variance(treatment_stat) / get_sample_size(treatment_stat)
        + (baseline.variance + control_mean_variance + 2 * baseline.difference_covariance),
        mean_denominator=baseline.mean,
        var_denominator=baseline.variance,
        covariance=baseline.variance + baseline.difference_covariance,
    )


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
        elif isinstance(statistic, QuantileStatistic):
            errors.extend(_validate_quantile(statistic))

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


def _validate_quantile(stat: QuantileStatistic) -> list[str]:
    """Validate QuantileStatistic."""
    errors = []

    if stat.has_zero_variance:
        errors.append("Quantile has zero variance - not enough events or too many tied values")
    if stat.has_tied_bound:
        errors.append("Quantile variance is unreliable - too many events tie with the quantile value")
    if stat.has_few_effective_clusters:
        errors.append("Quantile variance is unreliable - a few users produce most of the events")

    return errors


def validate_test_inputs(treatment_stat: AnyStatistic, control_stat: AnyStatistic) -> None:
    """
    Comprehensive validation of test inputs.

    Args:
        treatment_stat: Treatment group statistic
        control_stat: Control group statistic

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
