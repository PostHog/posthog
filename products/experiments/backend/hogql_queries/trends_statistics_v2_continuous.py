import numpy as np
from rest_framework.exceptions import ValidationError
from scipy.stats import t

from posthog.schema import ExperimentSignificanceCode, ExperimentVariantTrendsBaseStats

from posthog.exceptions_capture import capture_exception

from products.experiments.backend.hogql_queries import (
    EXPECTED_LOSS_SIGNIFICANCE_LEVEL,
    FF_DISTRIBUTION_THRESHOLD,
    MIN_PROBABILITY_FOR_SIGNIFICANCE,
)

# Prior parameters (minimal prior knowledge)
MU_0 = 0.0  # Prior mean
KAPPA_0 = 1.0  # Prior strength for mean
ALPHA_0 = 1.0  # Prior shape for variance
BETA_0 = 1.0  # Prior scale for variance

LOG_VARIANCE = 0.75

SAMPLE_SIZE = 10000
EPSILON = 1e-10  # Keeps log() finite when a mean is zero


def calculate_probabilities_v2_continuous(
    control_variant: ExperimentVariantTrendsBaseStats, test_variants: list[ExperimentVariantTrendsBaseStats]
) -> list[float]:
    """
    Estimate win probabilities for a continuous metric (for example revenue) by sampling from
    each variant's posterior.

    `count` holds the metric total, so the per-user mean is count / absolute_exposure. The model
    works in log-space to handle right-skewed values, with a Normal-Inverse-Gamma prior and a
    fixed log-space variance (LOG_VARIANCE).

    Index 0 is the probability that control beats the best test variant.
    Index i > 0 is the probability that test variant i-1 beats control.
    """
    if len(test_variants) >= 10:
        raise ValidationError("Can't calculate experiment results for more than 10 variants", code="too_much_data")
    if len(test_variants) < 1:
        raise ValidationError("Can't calculate experiment results for less than 2 variants", code="no_data")

    mean_value_control = control_variant.count / control_variant.absolute_exposure

    log_control_mean = np.log(mean_value_control + EPSILON)

    kappa_n_control = KAPPA_0 + control_variant.absolute_exposure
    mu_n_control = (KAPPA_0 * MU_0 + control_variant.absolute_exposure * log_control_mean) / kappa_n_control
    alpha_n_control = ALPHA_0 + control_variant.absolute_exposure / 2
    beta_n_control = BETA_0 + 0.5 * control_variant.absolute_exposure * LOG_VARIANCE

    control_posterior = t(
        df=2 * alpha_n_control, loc=mu_n_control, scale=np.sqrt(beta_n_control / (kappa_n_control * alpha_n_control))
    )
    samples_control = control_posterior.rvs(SAMPLE_SIZE)

    test_samples = []
    for test in test_variants:
        mean_value_test = test.count / test.absolute_exposure
        log_test_mean = np.log(mean_value_test + EPSILON)

        kappa_n_test = KAPPA_0 + test.absolute_exposure
        mu_n_test = (KAPPA_0 * MU_0 + test.absolute_exposure * log_test_mean) / kappa_n_test
        alpha_n_test = ALPHA_0 + test.absolute_exposure / 2
        beta_n_test = BETA_0 + 0.5 * test.absolute_exposure * LOG_VARIANCE

        test_posterior = t(
            df=2 * alpha_n_test, loc=mu_n_test, scale=np.sqrt(beta_n_test / (kappa_n_test * alpha_n_test))
        )
        test_samples.append(test_posterior.rvs(SAMPLE_SIZE))

    probabilities = []

    best_test_samples = np.max(test_samples, axis=0)
    control_wins = samples_control > best_test_samples
    probabilities.append(float(np.mean(control_wins)))

    for test_sample in test_samples:
        variant_wins = test_sample > samples_control
        probabilities.append(float(np.mean(variant_wins)))

    return probabilities


def are_results_significant_v2_continuous(
    control_variant: ExperimentVariantTrendsBaseStats,
    test_variants: list[ExperimentVariantTrendsBaseStats],
    probabilities: list[float],
) -> tuple[ExperimentSignificanceCode, float]:
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
        means = [v.count for v in all_variants]
        best_idx = np.argmax(means)
        best_variant = all_variants[best_idx]
        other_variants = all_variants[:best_idx] + all_variants[best_idx + 1 :]

        expected_loss = calculate_expected_loss_v2_continuous(best_variant, other_variants)

        if expected_loss >= EXPECTED_LOSS_SIGNIFICANCE_LEVEL:
            return ExperimentSignificanceCode.HIGH_LOSS, expected_loss

        return ExperimentSignificanceCode.SIGNIFICANT, expected_loss

    return ExperimentSignificanceCode.LOW_WIN_PROBABILITY, 1.0


def calculate_credible_intervals_v2_continuous(variants, lower_bound=0.025, upper_bound=0.975):
    """
    Credible interval of each variant's per-user mean. The interval is computed in log-space and
    transformed back to the original scale.

    Returns an empty dict if the calculation fails for any variant.
    """
    intervals = {}

    for variant in variants:
        try:
            mean_value = variant.count / variant.absolute_exposure
            log_mean = np.log(mean_value + EPSILON)

            kappa_n = KAPPA_0 + variant.absolute_exposure
            mu_n = (KAPPA_0 * MU_0 + variant.absolute_exposure * log_mean) / kappa_n
            alpha_n = ALPHA_0 + variant.absolute_exposure / 2
            beta_n = BETA_0 + 0.5 * variant.absolute_exposure * LOG_VARIANCE

            posterior = t(df=2 * alpha_n, loc=mu_n, scale=np.sqrt(beta_n / (kappa_n * alpha_n)))

            credible_interval = posterior.interval(upper_bound - lower_bound)

            intervals[variant.key] = (
                float(max(0, np.exp(credible_interval[0]) - EPSILON)),
                float(max(0, np.exp(credible_interval[1]) - EPSILON)),
            )
        except Exception as e:
            capture_exception(
                Exception(f"Error calculating credible interval for variant {variant.key}"),
                {"error": str(e)},
            )
            return {}

    return intervals


def calculate_expected_loss_v2_continuous(
    target_variant: ExperimentVariantTrendsBaseStats, variants: list[ExperimentVariantTrendsBaseStats]
) -> float:
    """
    Expected loss in per-user mean from choosing the target variant: the mean of
    max(0, best alternative - target) over posterior samples, in the original scale.
    """
    target_mean = target_variant.count / target_variant.absolute_exposure
    log_target_mean = np.log(target_mean + EPSILON)

    kappa_n_target = KAPPA_0 + target_variant.absolute_exposure
    mu_n_target = (KAPPA_0 * MU_0 + target_variant.absolute_exposure * log_target_mean) / kappa_n_target
    alpha_n_target = ALPHA_0 + target_variant.absolute_exposure / 2
    beta_n_target = BETA_0 + 0.5 * target_variant.absolute_exposure * LOG_VARIANCE

    target_posterior = t(
        df=2 * alpha_n_target, loc=mu_n_target, scale=np.sqrt(beta_n_target / (kappa_n_target * alpha_n_target))
    )
    target_samples = target_posterior.rvs(SAMPLE_SIZE)

    variant_samples = []
    for variant in variants:
        variant_mean = variant.count / variant.absolute_exposure
        log_variant_mean = np.log(variant_mean + EPSILON)

        kappa_n = KAPPA_0 + variant.absolute_exposure
        mu_n = (KAPPA_0 * MU_0 + variant.absolute_exposure * log_variant_mean) / kappa_n
        alpha_n = ALPHA_0 + variant.absolute_exposure / 2
        beta_n = BETA_0 + 0.5 * variant.absolute_exposure * LOG_VARIANCE

        variant_posterior = t(df=2 * alpha_n, loc=mu_n, scale=np.sqrt(beta_n / (kappa_n * alpha_n)))
        variant_samples.append(variant_posterior.rvs(SAMPLE_SIZE))

    target_samples = np.exp(target_samples) - EPSILON
    variant_samples = [np.exp(samples) - EPSILON for samples in variant_samples]

    variant_max = np.maximum.reduce(variant_samples)
    losses = np.maximum(0, variant_max - target_samples)
    expected_loss = float(np.mean(losses))

    return expected_loss
