"""
Analysis-health signals for experiments. Pure functions — no I/O.

Evaluates two signals: asymmetric `$multiple`-exclusion bias on uneven splits,
and a day-by-day sample ratio mismatch. Designed to grow (low exposures,
variant drift, ...) as additional pure evaluators when needed.
"""

from scipy.stats import chisquare

from posthog.schema import BiasRisk, DailySampleRatioMismatch, MultipleVariantHandling

from products.experiments.backend.variant_distribution import is_evenly_distributed

MULTIPLE_VARIANT_KEY = "$multiple"

# `$multiple` share above this triggers the warning. Below this, the asymmetric-
# exclusion effect on arm means is too small to matter in practice.
MULTIPLE_VARIANT_BIAS_THRESHOLD = 0.1  # on the 0-100 scale (0.1 = 0.1%)

# Minimum exposures on a single day before that day enters the daily SRM test.
SRM_DAILY_MINIMUM_SAMPLE_SIZE = 100


def evaluate_bias_risk(
    flag_variants: list[dict] | None,
    multiple_variant_handling: MultipleVariantHandling,
    total_exposures: dict[str, int],
) -> BiasRisk | None:
    """
    Empirically observed multi-variant exclusion bias risk: uneven split + EXCLUDE
    handling + observed `$multiple` share above the threshold.
    Returns a `BiasRisk` only when all three conditions hold; `None` otherwise.
    """
    if multiple_variant_handling != MultipleVariantHandling.EXCLUDE:
        return None

    variants = flag_variants or []
    if not variants:
        return None

    rollout_percentages = [variant.get("rollout_percentage", 0) for variant in variants]
    if is_evenly_distributed(rollout_percentages):
        return None

    total_observed = sum(total_exposures.values())
    if total_observed <= 0:
        return None

    multiple_observed = total_exposures.get(MULTIPLE_VARIANT_KEY, 0)
    multiple_variant_percentage = (multiple_observed / total_observed) * 100
    if multiple_variant_percentage <= MULTIPLE_VARIANT_BIAS_THRESHOLD:
        return None

    return BiasRisk(multiple_variant_percentage=multiple_variant_percentage)


def evaluate_daily_srm(
    daily_counts: dict[str, dict[str, int]],
    expected_ratios: dict[str, float],
) -> DailySampleRatioMismatch | None:
    """
    Run the chi-squared goodness-of-fit test on each day separately and return the
    worst day. `daily_counts` maps a variant key to per-day counts that are NOT
    cumulative. `expected_ratios` maps the same variant keys to their share of the
    split; the shares are normalised here, so they do not have to sum to 1.

    A variant can drift for a few days and still land on a healthy cumulative
    total, because an excess on one day cancels a shortfall on another. The daily
    test finds that drift.

    The reported p-value carries a Bonferroni correction: one test runs per day,
    so the smallest of N p-values must clear a bar that is N times stricter to mean
    the same thing. Without the correction a 30-day experiment would show a p below
    0.05 on some day about 8 times out of 10 with a perfectly healthy split.
    """
    if len(expected_ratios) < 2:
        return None

    total_ratio = sum(expected_ratios.values())
    if total_ratio <= 0:
        return None

    shares = [ratio / total_ratio for ratio in expected_ratios.values()]
    variant_series = [daily_counts.get(variant, {}) for variant in expected_ratios]

    day_p_values: dict[str, float] = {}
    all_days = sorted({day for counts in daily_counts.values() for day in counts})
    for day in all_days:
        observed = [float(series.get(day, 0)) for series in variant_series]
        day_total = sum(observed)
        # A day below the minimum cannot separate drift from ordinary daily noise,
        # and it can push an expected cell under the count the chi-squared test needs.
        if day_total < SRM_DAILY_MINIMUM_SAMPLE_SIZE:
            continue

        expected = [share * day_total for share in shares]
        _, p_value = chisquare(observed, expected)
        day_p_values[day] = float(p_value)

    if not day_p_values:
        return None

    worst_day = min(day_p_values, key=lambda day: day_p_values[day])
    return DailySampleRatioMismatch(
        date=worst_day,
        p_value=min(day_p_values[worst_day] * len(day_p_values), 1.0),
    )
