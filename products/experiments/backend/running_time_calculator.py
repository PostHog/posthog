"""Experiment running-time calculator.

Pure statistical helpers that estimate the recommended sample size and running
time for an experiment.

The sample-size formula uses the constant 16 ≈ 4 · 1.96², the multiplier for a
two-tailed test at 95% confidence and 80% power comparing two variants.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Literal

from products.experiments.stats.shared.statistics import RatioStatistic, SampleMeanStatistic, StatisticError

VARIANCE_SCALING_FACTOR_TOTAL_COUNT = 2
VARIANCE_SCALING_FACTOR_SUM = 0.25

# 4 · 1.96² ≈ 16: critical-value multiplier for 95% confidence / 80% power, two-tailed, two variants.
SAMPLE_SIZE_Z_FACTOR = 16
_POWER_Z = NormalDist().inv_cdf(0.8)

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
        return _finite(VARIANCE_SCALING_FACTOR_TOTAL_COUNT * baseline_value)
    if metric_type == "mean_sum_or_avg":
        return _finite(VARIANCE_SCALING_FACTOR_SUM * baseline_value * baseline_value)
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
    - ratio and retention: the analysis's delta method with covariance (``RatioStatistic``)
    """
    if metric_type in ("mean_count", "mean_sum_or_avg"):
        observed = _sample_variance(baseline) if baseline is not None else None
        return observed if observed is not None else calculate_variance(metric_type, baseline_value)

    if metric_type == "funnel":
        return None

    if metric_type in ("ratio", "retention"):
        if baseline is None or not baseline.denominator_sum or baseline.number_of_samples < 2:
            return None
        n = baseline.number_of_samples
        try:
            return _finite(
                RatioStatistic(
                    n=n,
                    m_statistic=SampleMeanStatistic(n=n, sum=baseline.sum, sum_squares=baseline.sum_squares),
                    d_statistic=SampleMeanStatistic(
                        n=n, sum=baseline.denominator_sum, sum_squares=baseline.denominator_sum_squares or 0
                    ),
                    m_d_sum_of_products=baseline.numerator_denominator_sum_product or 0,
                ).variance
            )
        except (StatisticError, ArithmeticError):
            return None

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

    if split is None:
        if number_of_variants < 2:
            return None
        # Every comparison of an even split is the same, so one share stands for all of them.
        control_share, variant_shares = 1 / number_of_variants, [1 / number_of_variants]
    else:
        shares = _normalized_shares(split)
        if shares is None:
            return None
        control_share, *variant_shares = shares
    comparisons = [
        comparison_sample_size(
            d,
            control_variance=variance,
            variant_variance=variance,
            control_share=control_share,
            variant_share=variant_share,
        )
        for variant_share in variant_shares
    ]
    if any(comparison is None for comparison in comparisons):
        return None
    sample_size = round_up_samples(max(comparison for comparison in comparisons if comparison is not None))

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
    value = _baseline_value(baseline, metric_type)
    return _finite(value) if value is not None else None


def _baseline_value(baseline: BaselineStats, metric_type: CalculatorMetricType) -> float | None:
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
    variant_variance: float | None = None,
    confidence_level: float = 0.95,
) -> float | None:
    """The smallest relative effect, as a percentage, that the sample-size formula detects between a control and a
    variant of these sizes.

    The inverse of :func:`calculate_sample_size`: for two variants of ``n`` samples each, the sample size for the
    returned effect is about ``2 · n``. The formula takes variants of equal size, so ``1/n_control + 1/n_variant``
    replaces its ``2/n`` for an uneven split. `variant_variance` defaults to the control's `variance`.
    """
    if control_samples <= 0 or variant_samples <= 0 or baseline_value == 0:
        return None

    if metric_type == "funnel" and variance is None:
        # A conversion rate of 0 or 1 has no binomial variance, so no effect size follows from it.
        if not 0 < baseline_value < 1:
            return None
        variance = baseline_value * (1 - baseline_value)
    elif variance is None:
        variance = calculate_variance(metric_type, baseline_value)
    if variance is None or variance <= 0:
        return None
    if variant_variance is None:
        variant_variance = variance

    d = math.sqrt(z_factor(confidence_level) / 2 * (variance / control_samples + variant_variance / variant_samples))
    return _finite(100 * d / abs(baseline_value))


def comparison_sample_size(
    difference: float,
    *,
    control_variance: float,
    variant_variance: float,
    control_share: float,
    variant_share: float,
    confidence_level: float = 0.95,
) -> float | None:
    """The exposures across all variants at which the comparison of one variant with the control detects an absolute
    `difference`, for each side's share of the exposures and its own variance.

    For two even variants with the same variance this is ``2 · 16 · variance / difference²``, twice the samples per
    variant of the classic formula. None when the inputs are too extreme to give a finite number.
    """
    denominator = difference * difference
    # A tiny difference underflows to 0 when squared.
    if denominator == 0:
        return None
    return _finite(
        z_factor(confidence_level)
        * (control_variance / control_share + variant_variance / variant_share)
        / 2
        / denominator
    )


def comparison_detectable_difference(
    samples: float,
    *,
    control_variance: float,
    variant_variance: float,
    control_share: float,
    variant_share: float,
    confidence_level: float = 0.95,
) -> float | None:
    """The absolute difference that the comparison of one variant with the control detects at `samples` exposures
    across all variants, split by each side's share. The inverse of :func:`comparison_sample_size`, so the detectable
    difference shrinks with the square root of the samples."""
    squared = z_factor(confidence_level) * (control_variance / control_share + variant_variance / variant_share) / 2
    # The delta method can return a negative variance, and stats without a spread a zero one. Neither has a detectable
    # difference, just as neither gets a target sample.
    if samples <= 0 or not squared > 0:
        return None
    return _finite(math.sqrt(squared / samples))


def z_factor(confidence_level: float) -> float:
    """The multiplier of the sample-size formula for a two-sided test at `confidence_level` with 80% power. It is
    `SAMPLE_SIZE_Z_FACTOR` at 95%, so that every estimate at 95% keeps its value."""
    if not 0 < confidence_level < 1:
        confidence_level = 0.95
    scale = (NormalDist().inv_cdf((1 + confidence_level) / 2) + _POWER_Z) / (NormalDist().inv_cdf(0.975) + _POWER_Z)
    return SAMPLE_SIZE_Z_FACTOR * scale**2


def round_up_samples(samples: float) -> int:
    # Float noise would otherwise turn an exact 3,200 into 3,201.
    return math.ceil(round(samples, 6))


def _normalized_shares(split: Sequence[float]) -> list[float] | None:
    total = sum(split)
    if len(split) < 2 or total <= 0 or any(share <= 0 for share in split):
        return None
    return [share / total for share in split]


def _sample_variance(baseline: BaselineStats) -> float | None:
    # Stats that don't fit together, such as a sum_squares the caller left at its default of 0, carry no variance.
    if baseline.number_of_samples < 2:
        return None
    try:
        return _finite(
            SampleMeanStatistic(
                n=baseline.number_of_samples, sum=baseline.sum, sum_squares=baseline.sum_squares
            ).variance
        )
    except (StatisticError, ArithmeticError):
        return None


def calculate_running_time_days(sample_size: int | None, exposure_rate_per_day: float | None) -> int | None:
    """Days to reach ``sample_size`` at ``exposure_rate_per_day`` exposures/day."""
    if not sample_size or not exposure_rate_per_day or exposure_rate_per_day <= 0:
        return None
    days = _finite(sample_size / exposure_rate_per_day)
    return math.ceil(days) if days is not None else None


def _finite(value: float) -> float | None:
    # Extreme inputs overflow to inf or come out as nan. Neither is an estimate, and JSON can't carry either.
    return value if math.isfinite(value) else None
