"""Experiment running-time calculator.

Pure statistical helpers that estimate the recommended sample size and running
time for an experiment. This mirrors the frontend calculator at
``frontend/src/scenes/experiments/RunningTimeCalculator/calculations.ts`` so the
same math is available server-side (e.g. for MCP tools).

The sample-size formula uses the constant 16 ≈ 4 · 1.96², the multiplier for a
two-tailed test at 95% confidence and 80% power comparing two variants.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from posthog.dataclasses import frozen

VARIANCE_SCALING_FACTOR_TOTAL_COUNT = 2
VARIANCE_SCALING_FACTOR_SUM = 0.25

# 4 · 1.96² ≈ 16: critical-value multiplier for 95% confidence / 80% power, two-tailed, two variants.
SAMPLE_SIZE_Z_FACTOR = 16

# Fallback MDE when neither the experiment nor the team sets one. Mirrors the frontend DEFAULT_MDE.
DEFAULT_MINIMUM_DETECTABLE_EFFECT = 30


def resolve_minimum_detectable_effect(saved_mde: float | None, team_default: float | None) -> float:
    """Resolve the MDE the same way the frontend does: experiment value, then team default, then 30.

    A zero or missing value at either level falls through to the next, so an experiment with no saved
    MDE still gets a usable estimate instead of an all-null result.
    """
    if saved_mde:
        return saved_mde
    if team_default:
        return team_default
    return DEFAULT_MINIMUM_DETECTABLE_EFFECT


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

    - mean metrics (count/sum): scaling factor on the baseline value
    - funnel: ``None`` (variance is implicit in p(1-p))
    - ratio and retention: delta method with covariance

    Delta method for ratio R = M/D::

        Var(R) ≈ Var(M)/D² + M²·Var(D)/D⁴ - 2·M·Cov(M,D)/D³
    """
    if metric_type in ("mean_count", "mean_sum_or_avg"):
        return calculate_variance(metric_type, baseline_value)

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
) -> int | None:
    """Total recommended sample size across all variants.

    ``mde`` is a percentage (e.g. ``5`` for a 5% minimum detectable effect). For
    ratio/retention metrics ``variance`` must be supplied (see
    :func:`calculate_variance_from_stats`); for mean metrics it is derived from
    ``baseline_value`` when omitted.
    """
    if mde == 0:
        return None

    d = (mde / 100) * baseline_value
    if d == 0:
        return None

    if metric_type == "funnel":
        # Binomial metric: N = (16 · p · (1 - p)) / d²
        sample_size_formula = (SAMPLE_SIZE_Z_FACTOR * baseline_value * (1 - baseline_value)) / d**2
    else:
        if variance is None:
            variance = calculate_variance(metric_type, baseline_value)
        if variance is None:
            return None
        # Count / Sum / Ratio / Retention: N = (16 · variance) / d²
        sample_size_formula = (SAMPLE_SIZE_Z_FACTOR * variance) / d**2

    sample_size = math.ceil(sample_size_formula * number_of_variants)

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


def calculate_recommended_sample_size(
    metric_type: CalculatorMetricType,
    mde: float,
    baseline_value: float,
    number_of_variants: int,
    baseline: BaselineStats | None = None,
) -> int | None:
    """Recommended sample size for any metric type, deriving variance as needed."""
    if metric_type in ("ratio", "retention"):
        variance = calculate_variance_from_stats(baseline_value, metric_type, baseline)
        return calculate_sample_size(metric_type, baseline_value, mde, number_of_variants, variance)

    return calculate_sample_size(metric_type, baseline_value, mde, number_of_variants)


def calculate_running_time_days(sample_size: int | None, exposure_rate_per_day: float | None) -> int | None:
    """Days to reach ``sample_size`` at ``exposure_rate_per_day`` exposures/day."""
    if not sample_size or not exposure_rate_per_day or exposure_rate_per_day <= 0:
        return None
    return math.ceil(sample_size / exposure_rate_per_day)


def baseline_stats_from_result_blob(result: dict[str, Any]) -> BaselineStats | None:
    """Map a stored metric result blob's control baseline into :class:`BaselineStats`.

    Mirrors the frontend ``baselineStatsFromResults``. The blob is a model-dumped
    ``ExperimentQueryResponse`` (post ``strip_step_sessions``); its ``baseline`` object
    carries the same snake_case keys. Returns ``None`` when the blob has no usable baseline.
    """
    baseline = result.get("baseline")
    if not isinstance(baseline, dict) or baseline.get("number_of_samples") is None:
        return None

    return BaselineStats(
        number_of_samples=baseline["number_of_samples"],
        sum=baseline.get("sum", 0.0),
        sum_squares=baseline.get("sum_squares", 0.0),
        denominator_sum=baseline.get("denominator_sum"),
        denominator_sum_squares=baseline.get("denominator_sum_squares"),
        numerator_denominator_sum_product=baseline.get("numerator_denominator_sum_product"),
        step_counts=baseline.get("step_counts") or [],
    )


def select_sizing_metric(
    metrics: list[dict[str, Any]] | None,
    ordered_uuids: Sequence[str] | None,
) -> tuple[dict[str, Any], CalculatorMetricType] | None:
    """Pick the first primary metric to size the experiment on, in display order.

    Classifies it the same way the frontend ``getCalculatorMetricType`` does. Returns the
    metric dict and its calculator type, or ``None`` when there is no usable primary metric.
    """
    if not metrics:
        return None

    order = {uuid: index for index, uuid in enumerate(ordered_uuids or [])}
    fallback = len(order)

    # Sort by the metric's saved display rank, falling back to list order for metrics not in the ordering.
    ordered_metrics = sorted(metrics, key=lambda metric: order.get(metric.get("uuid", ""), fallback))

    for metric in ordered_metrics:
        calc_type = _calculator_metric_type(metric)
        if calc_type is not None:
            return metric, calc_type
    return None


def _calculator_metric_type(metric: dict[str, Any]) -> CalculatorMetricType | None:
    metric_type = metric.get("metric_type")
    if metric_type == "funnel":
        return "funnel"
    if metric_type == "ratio":
        return "ratio"
    if metric_type == "retention":
        return "retention"
    if metric_type == "mean":
        math_value = (metric.get("source") or {}).get("math")
        return "mean_sum_or_avg" if math_value == "sum" else "mean_count"
    return None


@frozen
class RunningTimeEstimate:
    """Derived running-time state for one experiment, computed from live results or manual config."""

    target_sample_size: int | None
    current_exposures: int | None
    remaining_days: int | None


def current_exposures_from_result_blob(result: dict[str, Any] | None) -> int | None:
    """Total exposed users across control and every variant, or ``None`` when the blob is unusable."""
    if not result:
        return None
    baseline = result.get("baseline")
    if not isinstance(baseline, dict) or baseline.get("number_of_samples") is None:
        return None
    total = baseline["number_of_samples"]
    for variant in result.get("variant_results") or []:
        if isinstance(variant, dict) and variant.get("number_of_samples") is not None:
            total += variant["number_of_samples"]
    return total


def _days_elapsed(start_date: datetime | None, now: datetime) -> float | None:
    if start_date is None:
        return None
    return (now - start_date).total_seconds() / 86400


def _remaining_days(
    target_sample_size: int | None,
    current_exposures: int | None,
    rate_per_day: float | None,
    days_elapsed: float | None,
) -> int | None:
    """Days to reach the target, mirroring the frontend ``remainingDays`` selector."""
    if not target_sample_size or target_sample_size <= 0 or not rate_per_day or rate_per_day <= 0:
        return None

    # Not enough live data yet: show the total estimated time from the rate alone.
    if not days_elapsed or days_elapsed < 1 or not current_exposures or current_exposures < 100:
        return math.ceil(target_sample_size / rate_per_day)

    if current_exposures >= target_sample_size:
        return 0

    return math.ceil((target_sample_size - current_exposures) / rate_per_day)


def estimate_running_time_for_experiment(
    *,
    metrics: list[dict[str, Any]] | None,
    primary_metrics_ordered_uuids: Sequence[str] | None,
    running_time_calculation: dict[str, Any] | None,
    start_date: datetime | None,
    number_of_variants: int,
    result_blob: dict[str, Any] | None,
    now: datetime,
    mde_override: float | None = None,
) -> RunningTimeEstimate:
    """Estimate sample size, current exposures, and remaining days for one experiment.

    Manual mode reads the saved exposure-estimate config; automatic mode derives the baseline
    and exposure rate from ``result_blob`` (the latest metric result). Mirrors the frontend
    ``runningTimeLogic`` so the list matches the detail page.
    """
    config = running_time_calculation or {}
    exposure_config = config.get("exposure_estimate_config") or {}
    is_manual = exposure_config.get("conversionRateInputType") == "manual"
    mde = mde_override if mde_override is not None else config.get("minimum_detectable_effect")

    if mde is None or mde <= 0:
        return RunningTimeEstimate(target_sample_size=None, current_exposures=None, remaining_days=None)

    if is_manual:
        return _estimate_manual(exposure_config, mde, number_of_variants, start_date, result_blob, now)

    return _estimate_automatic(
        metrics=metrics,
        primary_metrics_ordered_uuids=primary_metrics_ordered_uuids,
        mde=mde,
        start_date=start_date,
        number_of_variants=number_of_variants,
        result_blob=result_blob,
        now=now,
    )


def _estimate_manual(
    exposure_config: dict[str, Any],
    mde: float,
    number_of_variants: int,
    start_date: datetime | None,
    result_blob: dict[str, Any] | None,
    now: datetime,
) -> RunningTimeEstimate:
    raw_metric_type = exposure_config.get("manualMetricType")
    metric_type: ManualCalculatorMetricType = (
        raw_metric_type if raw_metric_type in ("funnel", "mean_count", "mean_sum_or_avg") else "funnel"
    )
    baseline_value = exposure_config.get("manualBaselineValue")
    exposure_rate = exposure_config.get("manualExposureRate")

    if baseline_value is None or baseline_value <= 0:
        return RunningTimeEstimate(target_sample_size=None, current_exposures=None, remaining_days=None)

    # Funnel baseline is entered as a percentage; the calculator wants a 0-1 rate.
    resolved_baseline = baseline_value / 100 if metric_type == "funnel" else baseline_value
    target = calculate_recommended_sample_size(metric_type, mde, resolved_baseline, number_of_variants)

    # The detail page subtracts live exposures even in manual mode; the only manual-specific input is the
    # fixed exposure rate. Mirror that so the list agrees with the detail page.
    current_exposures = current_exposures_from_result_blob(result_blob)
    remaining = _remaining_days(target, current_exposures, exposure_rate, _days_elapsed(start_date, now))
    return RunningTimeEstimate(target_sample_size=target, current_exposures=current_exposures, remaining_days=remaining)


def _estimate_automatic(
    *,
    metrics: list[dict[str, Any]] | None,
    primary_metrics_ordered_uuids: Sequence[str] | None,
    mde: float,
    start_date: datetime | None,
    number_of_variants: int,
    result_blob: dict[str, Any] | None,
    now: datetime,
) -> RunningTimeEstimate:
    empty = RunningTimeEstimate(target_sample_size=None, current_exposures=None, remaining_days=None)

    selected = select_sizing_metric(metrics, primary_metrics_ordered_uuids)
    baseline = baseline_stats_from_result_blob(result_blob) if result_blob else None
    if selected is None or baseline is None:
        return empty

    _, metric_type = selected
    if metric_type in ("ratio", "retention") and not baseline.denominator_sum:
        return empty

    baseline_value = calculate_baseline_value(baseline, metric_type)
    if baseline_value is None:
        return empty

    target = calculate_recommended_sample_size(metric_type, mde, baseline_value, number_of_variants, baseline)
    current_exposures = current_exposures_from_result_blob(result_blob)

    days_elapsed = _days_elapsed(start_date, now)
    rate_per_day = (
        current_exposures / days_elapsed if current_exposures and days_elapsed and days_elapsed >= 0.1 else None
    )
    remaining = _remaining_days(target, current_exposures, rate_per_day, days_elapsed)
    return RunningTimeEstimate(target_sample_size=target, current_exposures=current_exposures, remaining_days=remaining)
