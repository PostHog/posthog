import numpy as np
from rest_framework.exceptions import ValidationError
from scipy.stats import gamma

from posthog.schema import ExperimentSignificanceCode, ExperimentVariantTrendsBaseStats

from posthog.exceptions_capture import capture_exception

from products.experiments.backend.hogql_queries import (
    EXPECTED_LOSS_SIGNIFICANCE_LEVEL,
    FF_DISTRIBUTION_THRESHOLD,
    MIN_PROBABILITY_FOR_SIGNIFICANCE,
)

Probability = float

# Prior parameters (minimal prior knowledge)
ALPHA_0 = 1
BETA_0 = 1
SAMPLE_SIZE = 10000


def calculate_probabilities_v2_count(
    control_variant: ExperimentVariantTrendsBaseStats, test_variants: list[ExperimentVariantTrendsBaseStats]
) -> list[float]:
    """
    Estimate win probabilities by sampling from each variant's Gamma posterior
    (Gamma-Poisson model with a Gamma(1, 1) prior).

    Index 0 is the probability that control beats the best test variant.
    Index i > 0 is the probability that test variant i-1 beats control.
    """
    if len(test_variants) >= 10:
        raise ValidationError("Can't calculate experiment results for more than 10 variants", code="too_much_data")
    if len(test_variants) < 1:
        raise ValidationError("Can't calculate experiment results for less than 2 variants", code="no_data")

    alpha_control = ALPHA_0 + control_variant.count
    beta_control = BETA_0 + control_variant.absolute_exposure

    samples_control = gamma.rvs(alpha_control, scale=1 / beta_control, size=SAMPLE_SIZE)

    test_samples = []
    for test in test_variants:
        alpha_test = ALPHA_0 + test.count
        beta_test = BETA_0 + test.absolute_exposure
        test_samples.append(gamma.rvs(alpha_test, scale=1 / beta_test, size=SAMPLE_SIZE))

    probabilities = []

    best_test_samples = np.max(test_samples, axis=0)
    control_wins = samples_control > best_test_samples
    probabilities.append(float(np.mean(control_wins)))

    for test_sample in test_samples:
        variant_wins = test_sample > samples_control
        probabilities.append(float(np.mean(variant_wins)))

    return probabilities


def are_results_significant_v2_count(
    control_variant: ExperimentVariantTrendsBaseStats,
    test_variants: list[ExperimentVariantTrendsBaseStats],
    probabilities: list[Probability],
) -> tuple[ExperimentSignificanceCode, Probability]:
    """
    Return (significance code, expected loss). The expected loss is 1.0 for any result that is not significant.
    """
    for variant in test_variants:
        if variant.absolute_exposure < FF_DISTRIBUTION_THRESHOLD:
            return ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, 1.0

    if control_variant.absolute_exposure < FF_DISTRIBUTION_THRESHOLD:
        return ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, 1.0

    max_probability = max(probabilities)

    if max_probability >= MIN_PROBABILITY_FOR_SIGNIFICANCE:
        all_variants = [control_variant, *test_variants]
        rates = [v.count / v.absolute_exposure for v in all_variants]
        best_idx = np.argmax(rates)
        best_variant = all_variants[best_idx]
        other_variants = all_variants[:best_idx] + all_variants[best_idx + 1 :]

        expected_loss = calculate_expected_loss_v2_count(best_variant, other_variants)

        if expected_loss >= EXPECTED_LOSS_SIGNIFICANCE_LEVEL:
            return ExperimentSignificanceCode.HIGH_LOSS, expected_loss

        return ExperimentSignificanceCode.SIGNIFICANT, expected_loss

    return ExperimentSignificanceCode.LOW_WIN_PROBABILITY, 1.0


def calculate_credible_intervals_v2_count(variants, lower_bound=0.025, upper_bound=0.975):
    """
    Credible interval of each variant's rate (events per exposure), from its Gamma posterior.

    Returns an empty dict if the calculation fails for any variant.
    """
    intervals = {}

    for variant in variants:
        try:
            alpha_posterior = ALPHA_0 + variant.count
            beta_posterior = BETA_0 + variant.absolute_exposure

            credible_interval = gamma.ppf([lower_bound, upper_bound], alpha_posterior, scale=1 / beta_posterior)

            intervals[variant.key] = (float(credible_interval[0]), float(credible_interval[1]))
        except Exception as e:
            capture_exception(
                Exception(f"Error calculating credible interval for variant {variant.key}"),
                {"error": str(e)},
            )
            return {}

    return intervals


def calculate_expected_loss_v2_count(
    target_variant: ExperimentVariantTrendsBaseStats, variants: list[ExperimentVariantTrendsBaseStats]
) -> float:
    """
    Expected loss in rate from choosing the target variant: the mean of
    max(0, best alternative - target) over posterior samples.

    Gamma is the conjugate prior of the Poisson rate, so each posterior is
    Gamma(ALPHA_0 + count, BETA_0 + absolute_exposure).
    """
    target_alpha = ALPHA_0 + target_variant.count
    target_beta = BETA_0 + target_variant.absolute_exposure

    target_samples = gamma.rvs(target_alpha, scale=1 / target_beta, size=SAMPLE_SIZE)

    variant_samples = []
    for variant in variants:
        alpha = ALPHA_0 + variant.count
        beta = BETA_0 + variant.absolute_exposure
        samples = gamma.rvs(alpha, scale=1 / beta, size=SAMPLE_SIZE)
        variant_samples.append(samples)

    variant_max = np.maximum.reduce(variant_samples)
    losses = np.maximum(0, variant_max - target_samples)
    expected_loss = float(np.mean(losses))

    return expected_loss
