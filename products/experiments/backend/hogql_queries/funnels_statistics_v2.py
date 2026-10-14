import numpy as np
from scipy import stats
from scipy.stats import betabinom

from posthog.schema import ExperimentSignificanceCode, ExperimentVariantFunnelsBaseStats

from products.experiments.backend.hogql_queries import (
    EXPECTED_LOSS_SIGNIFICANCE_LEVEL,
    FF_DISTRIBUTION_THRESHOLD,
    MIN_PROBABILITY_FOR_SIGNIFICANCE,
)

ALPHA_PRIOR = 1
BETA_PRIOR = 1
SAMPLE_SIZE = 10000


def calculate_probabilities_v2(
    control: ExperimentVariantFunnelsBaseStats, variants: list[ExperimentVariantFunnelsBaseStats]
) -> list[float]:
    """
    Monte Carlo win probabilities for funnel conversion rates.

    The Beta distribution is the conjugate prior for binomial (success/failure) data,
    so the posterior is also a Beta distribution and is easy to sample. The prior is
    Beta(1,1), which is uniform over [0, 1].

    Index 0 of the result is the probability that control beats the best test variant.
    Index i > 0 is the probability that test variant i-1 beats control.
    """
    all_variants = [control, *variants]

    samples: list[np.ndarray] = []
    for variant in all_variants:
        alpha = ALPHA_PRIOR + variant.success_count
        beta = BETA_PRIOR + variant.failure_count
        variant_samples = np.random.beta(alpha, beta, SAMPLE_SIZE)
        samples.append(variant_samples)

    samples_array = np.array(samples)
    probabilities = []
    control_samples = samples_array[0]

    # Find the best test variant at each sample point
    test_variants_samples = samples_array[1:]
    best_variant_samples = np.max(test_variants_samples, axis=0)

    control_prob = np.mean(control_samples >= best_variant_samples)
    probabilities.append(float(control_prob))

    for i in range(1, len(all_variants)):
        probability = np.mean(samples_array[i] > control_samples)
        probabilities.append(float(probability))

    return probabilities


def calculate_expected_loss_v2(
    target_variant: ExperimentVariantFunnelsBaseStats, variants: list[ExperimentVariantFunnelsBaseStats]
) -> float:
    """
    Expected loss in conversion rate when the target variant is chosen over the best
    of the other variants, from Beta-Binomial posterior samples.
    """
    target_alpha = int(ALPHA_PRIOR + target_variant.success_count)
    target_beta = int(BETA_PRIOR + target_variant.failure_count)
    target_n = int(target_variant.success_count + target_variant.failure_count)

    target_samples = betabinom.rvs(target_n, target_alpha, target_beta, size=SAMPLE_SIZE) / target_n

    variant_samples = []
    for variant in variants:
        n = int(variant.success_count + variant.failure_count)
        alpha = int(ALPHA_PRIOR + variant.success_count)
        beta = int(BETA_PRIOR + variant.failure_count)
        samples = betabinom.rvs(n, alpha, beta, size=SAMPLE_SIZE) / n
        variant_samples.append(samples)

    variant_max = np.maximum.reduce(variant_samples)
    losses = np.maximum(0, variant_max - target_samples)
    expected_loss = float(np.mean(losses))

    return expected_loss


def are_results_significant_v2(
    control: ExperimentVariantFunnelsBaseStats,
    variants: list[ExperimentVariantFunnelsBaseStats],
    probabilities: list[float],
) -> tuple[ExperimentSignificanceCode, float]:
    """
    Returns the significance code and the expected loss of the variant with the
    highest conversion rate. The expected loss is 1.0 when a check fails before
    the loss calculation.
    """
    if control.success_count + control.failure_count < FF_DISTRIBUTION_THRESHOLD or any(
        v.success_count + v.failure_count < FF_DISTRIBUTION_THRESHOLD for v in variants
    ):
        return ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, 1.0

    max_probability = max(probabilities)
    if max_probability >= MIN_PROBABILITY_FOR_SIGNIFICANCE:
        all_variants = [control, *variants]
        conversion_rates = [v.success_count / (v.success_count + v.failure_count) for v in all_variants]
        best_idx = np.argmax(conversion_rates)
        best_variant = all_variants[best_idx]
        other_variants = all_variants[:best_idx] + all_variants[best_idx + 1 :]
        expected_loss = calculate_expected_loss_v2(best_variant, other_variants)

        if expected_loss >= EXPECTED_LOSS_SIGNIFICANCE_LEVEL:
            return ExperimentSignificanceCode.HIGH_LOSS, expected_loss

        return ExperimentSignificanceCode.SIGNIFICANT, expected_loss

    return ExperimentSignificanceCode.LOW_WIN_PROBABILITY, 1.0


def calculate_credible_intervals_v2(variants: list[ExperimentVariantFunnelsBaseStats]) -> dict[str, list[float]]:
    """95% credible intervals for each variant's conversion rate, from the Beta posterior with a Beta(1,1) prior."""
    intervals = {}

    for variant in variants:
        alpha = ALPHA_PRIOR + variant.success_count
        beta = BETA_PRIOR + variant.failure_count

        lower, upper = stats.beta.ppf([0.025, 0.975], alpha, beta)

        intervals[variant.key] = [float(lower), float(upper)]

    return intervals
