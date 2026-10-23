"""Experiment running-time calculator.

Pure statistical helpers that estimate the recommended sample size and running
time for an experiment.

The sample-size formula uses the constant 16 ≈ 4 · 1.96², the multiplier for a
two-tailed test at 95% confidence and 80% power comparing two variants.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from products.experiments.stats.shared.statistics import SampleMeanStatistic, StatisticError

VARIANCE_SCALING_FACTOR_TOTAL_COUNT = 2
VARIANCE_SCALING_FACTOR_SUM = 0.25

# 4 · 1.96² ≈ 16: critical-value multiplier for 95% confidence / 80% power, two-tailed, two variants.
SAMPLE_SIZE_Z_FACTOR = 16

# Manual calculator only supports these types (ratio/retention require full baseline data).
ManualCalculatorMetricType = Literal["funnel", "mean_count", "mean_sum_or_avg"]
# Full calculator supports all metric types.
CalculatorMetricType = Literal["funnel", "mean_count", "mean_sum_or_avg", "ratio", "retention"]

METRIC_TYPE_CHOICES = ["funnel", "mean_count", "mean_sum_or_avg", "ratio", "retention"]


@dataclass
class BaselineStats:
    """Sufficient statistics for the control group, mirroring the frontend ``baseline`` object."""

    number_of_samples: int
    sum: float
    sum_squares: float = 0.0
    denominator_sum: float | None = None
    denominator_sum_squares: float | None = None
    numerator_denominator_sum_product: float | None = None
    step_counts: list[float] = field(default_factory=list)


def calculate_variance(metric_type: CalculatorMetricType, baseline_value: float) -> float | None:
    """Variance from a single baseline value.

    Only funnel / mean_count / mean_sum_or_avg can be derived from the baseline
    value alone — ratio and retention need full baseline statistics (use
    :func:`calculate_variance_from_stats`).
    """
    if metric_type == "mean_count":
        return VARIANCE_SCALING_FACTOR_TOTAL_COUNT * baseline_value
    if metric_type == "mean_sum_or_avg":
        return VARIANCE_SCALING_FACTOR_SUM * baseline_value**2
    # funnel: variance is embedded in the p(1-p) sample-size formula; ratio/retention need stats.
    return None


def calculate_variance_from_stats(
    baseline_value: float,
    metric_type: CalculatorMetricType,
    baseline: BaselineStats | None = None,
) -> float | None:
    """Variance from full baseline statistics.

    - mean metrics: the sample variance of the stats, as the analysis computes it. Without usable stats, a scaling
      factor on the baseline value
    - funnel: ``None`` (variance is implicit in p(1-p))
    - ratio and retention: delta method with covariance

    Delta method for ratio R = M/D::

        Var(R) ≈ Var(M)/D² + M²·Var(D)/D⁴ - 2·M·Cov(M,D)/D³
    """
    if metric_type in ("mean_count", "mean_sum_or_avg"):
        observed = _sample_variance(baseline) if baseline is not None else None
        return observed if observed is not None else calculate_variance(metric_type, baseline_value)

    if metric_type == "funnel":
        return None

    if metric_type in ("ratio", "retention"):
        if baseline is None or not baseline.denominator_sum:
            return None

        n = baseline.number_of_samples
        if n == 0:
            return None

        # Means for numerator (M) and denominator (D).
        mean_m = baseline.sum / n
        mean_d = baseline.denominator_sum / n

        # Variances via Var(X) = E[X²] - E[X]².
        var_m = baseline.sum_squares / n - mean_m**2
        var_d = (baseline.denominator_sum_squares or 0) / n - mean_d**2

        # Covariance: Cov(M,D) = E[MD] - E[M]·E[D].
        cov = (baseline.numerator_denominator_sum_product or 0) / n - mean_m * mean_d

        return var_m / mean_d**2 + (mean_m**2 * var_d) / mean_d**4 - (2 * mean_m * cov) / mean_d**3

    return None


def calculate_sample_size(
    metric_type: CalculatorMetricType,
    baseline_value: float,
    mde: float,
    number_of_variants: int,
    variance: float | None = None,
    split: Sequence[float] | None = None,
) -> int | None:
    """Total recommended sample size across all variants.

    ``mde`` is a percentage (e.g. ``5`` for a 5% minimum detectable effect). For
    ratio/retention metrics ``variance`` must be supplied (see
    :func:`calculate_variance_from_stats`); for mean metrics it is derived from
    ``baseline_value`` when omitted, and for funnels from p(1-p).

    ``split`` holds the traffic shares of the analyzed variants with the control first, in any unit. Without it, the
    ``number_of_variants`` variants get equal shares.
    """
    if mde == 0:
        return None

    d = (mde / 100) * baseline_value
    if d == 0:
        return None

    if variance is None:
        if metric_type == "funnel":
            variance = baseline_value * (1 - baseline_value)
        else:
            variance = calculate_variance(metric_type, baseline_value)
    if variance is None:
        return None
    # Samples per variant for two equal variants: N = (16 · variance) / d²
    sample_size_formula = (SAMPLE_SIZE_Z_FACTOR * variance) / d**2

    multiplier = _split_multiplier(split if split is not None else [1.0] * number_of_variants)
    if multiplier is None:
        return None
    sample_size = math.ceil(sample_size_formula * multiplier)

    # A funnel baseline above 1 flips the (1 - p) term negative, and the delta method can return a
    # negative variance for ratio/retention. Both make the sample size non-positive, which has no
    # meaning as a count and downstream renders as a negative running time. Treat it as no estimate.
    if sample_size <= 0:
        return None

    return sample_size


def calculate_baseline_value(baseline: BaselineStats, metric_type: CalculatorMetricType) -> float | None:
    """Derive the baseline metric value from raw statistics.

    Returns: avg events/user (count), avg property value/user (sum), conversion
    rate (funnel), or the ratio (ratio/retention).
    """
    if baseline.number_of_samples == 0:
        return None

    if metric_type in ("mean_count", "mean_sum_or_avg"):
        return baseline.sum / baseline.number_of_samples

    if metric_type == "funnel":
        step_counts = baseline.step_counts
        if not step_counts:
            # Fall back to sum / number_of_samples when step_counts is unavailable.
            return baseline.sum / baseline.number_of_samples
        # Conversion rate is (completed final step) / (total exposed).
        return step_counts[-1] / baseline.number_of_samples

    if metric_type in ("ratio", "retention"):
        # Both use denominator_sum: retention = completions / starters, ratio = numerator / denominator.
        if not baseline.denominator_sum:
            return None
        return baseline.sum / baseline.denominator_sum

    return None


def calculate_detectable_effect(
    metric_type: CalculatorMetricType,
    baseline_value: float,
    control_samples: int,
    variant_samples: int,
    variance: float | None = None,
) -> float | None:
    """The smallest relative effect, as a percentage, that the sample-size formula detects between a control and a
    variant of these sizes.

    The inverse of :func:`calculate_sample_size`: for two variants of ``n`` samples each, the sample size for the
    returned effect is about ``2 · n``. The formula takes variants of equal size, so ``1/n_control + 1/n_variant``
    replaces its ``2/n`` for an uneven split.
    """
    if control_samples <= 0 or variant_samples <= 0 or baseline_value == 0:
        return None

    if metric_type == "funnel":
        # A conversion rate of 0 or 1 has no binomial variance, so no effect size follows from it.
        if not 0 < baseline_value < 1:
            return None
        variance = baseline_value * (1 - baseline_value)
    elif variance is None:
        variance = calculate_variance(metric_type, baseline_value)
    if variance is None or variance <= 0:
        return None

    d = math.sqrt(SAMPLE_SIZE_Z_FACTOR / 2 * variance * (1 / control_samples + 1 / variant_samples))
    return 100 * d / abs(baseline_value)


def _split_multiplier(split: Sequence[float]) -> float | None:
    """The total sample, in samples per variant of an even two-variant test, that gives every comparison with the
    control the power of that test.

    A comparison of a control and a variant with shares ``q_c`` and ``q_v`` of a total ``N`` has the variance of an
    even comparison with ``2 / (1/q_c + 1/q_v)`` of ``N`` per variant. The comparison with the smallest variant needs
    the largest total. For ``k`` equal shares the multiplier is ``k``.
    """
    total = sum(split)
    if len(split) < 2 or total <= 0 or any(share <= 0 for share in split):
        return None
    control, *variants = (share / total for share in split)
    return max((1 / control + 1 / variant) / 2 for variant in variants)


def _sample_variance(baseline: BaselineStats) -> float | None:
    # Stats that don't fit together, such as a sum_squares the caller left at its default of 0, carry no variance.
    if baseline.number_of_samples < 2:
        return None
    try:
        return SampleMeanStatistic(
            n=baseline.number_of_samples, sum=baseline.sum, sum_squares=baseline.sum_squares
        ).variance
    except StatisticError:
        return None


def calculate_running_time_days(sample_size: int | None, exposure_rate_per_day: float | None) -> int | None:
    """Days to reach ``sample_size`` at ``exposure_rate_per_day`` exposures/day."""
    if not sample_size or not exposure_rate_per_day or exposure_rate_per_day <= 0:
        return None
    return math.ceil(sample_size / exposure_rate_per_day)
