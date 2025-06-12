"""
Core Bayesian calculation utilities for A/B testing.

This module provides fundamental Bayesian statistical calculations including
posterior updates, credible intervals, probability calculations, and risk assessment.
"""

from typing import Union
import numpy as np
from scipy.stats import norm, truncnorm

from ..shared.statistics import SampleMeanStatistic, ProportionStatistic, StatisticError
from ..shared.enums import DifferenceType
from ..shared.utils import get_mean, get_variance, get_sample_size

from .priors import GaussianPrior


def calculate_effect_size_and_variance(
    treatment_stat: Union[SampleMeanStatistic, ProportionStatistic],
    control_stat: Union[SampleMeanStatistic, ProportionStatistic],
    difference_type: DifferenceType,
) -> tuple[float, float]:
    """
    Calculate effect size and its variance for Bayesian analysis.

    Args:
        treatment_stat: Treatment group statistic
        control_stat: Control group statistic
        difference_type: Type of difference to calculate

    Returns:
        Tuple of (effect_size, effect_variance)

    Raises:
        StatisticError: If control mean is zero for relative calculations
    """
    treatment_mean = get_mean(treatment_stat)
    control_mean = get_mean(control_stat)
    treatment_var = get_variance(treatment_stat)
    control_var = get_variance(control_stat)
    treatment_n = get_sample_size(treatment_stat)
    control_n = get_sample_size(control_stat)

    if difference_type == DifferenceType.ABSOLUTE:
        # Absolute difference: μ_T - μ_C
        effect = treatment_mean - control_mean
        effect_variance = treatment_var / treatment_n + control_var / control_n

    elif difference_type == DifferenceType.RELATIVE:
        if control_mean <= 0:
            raise StatisticError("Control mean must be positive for relative difference calculation")

        # Direct relative difference: (μ_T - μ_C) / μ_C
        effect = (treatment_mean - control_mean) / control_mean

        # Using delta method for ratios
        effect_variance = variance_of_ratios(
            mean_m=treatment_mean,
            var_m=treatment_var / treatment_n,
            mean_d=control_mean,
            var_d=control_var / control_n,
            covariance=0,  # No covariance between treatment and control
        )

    else:
        raise StatisticError(f"Unsupported difference type: {difference_type}")

    return effect, effect_variance


def variance_of_ratios(mean_m: float, var_m: float, mean_d: float, var_d: float, covariance: float) -> float:
    """
    Calculate variance of ratio using delta method.

    For ratio R = M/D, the variance is approximately:
    Var(R) ≈ Var(M)/D² + M²Var(D)/D⁴ - 2M*Cov(M,D)/D³

    Args:
        mean_m: Mean of numerator
        var_m: Variance of numerator
        mean_d: Mean of denominator
        var_d: Variance of denominator
        covariance: Covariance between numerator and denominator

    Returns:
        Variance of the ratio
    """
    if abs(mean_d) < 1e-10:
        raise StatisticError("Denominator mean cannot be zero for ratio variance calculation")

    return var_m / mean_d**2 + mean_m**2 * var_d / mean_d**4 - 2 * mean_m * covariance / mean_d**3


def calculate_posterior(effect_size: float, effect_variance: float, prior: GaussianPrior) -> tuple[float, float]:
    """
    Calculate posterior distribution parameters using Bayesian updating.

    For Gaussian prior and Gaussian likelihood:
    - Prior: μ ~ N(μ₀, σ₀²)
    - Likelihood: x̄ ~ N(μ, σ²)
    - Posterior: μ ~ N(μₙ, σₙ²)

    Where:
    - Posterior precision: τₙ = τ₀ + τ_data
    - Posterior mean: μₙ = (τ₀μ₀ + τ_data·x̄) / τₙ
    - Posterior variance: σₙ² = 1/τₙ

    Args:
        effect_size: Observed effect size (sample mean)
        effect_variance: Variance of effect size estimate
        prior: Gaussian prior distribution

    Returns:
        Tuple of (posterior_mean, posterior_variance)
    """
    if effect_variance <= 0:
        raise StatisticError("Effect variance must be positive")

    # Data precision (inverse of variance)
    data_precision = 1.0 / effect_variance

    # Prior precision (0 for non-informative priors)
    prior_precision = prior.precision

    # Posterior precision
    posterior_precision = prior_precision + data_precision

    if posterior_precision <= 0:
        raise StatisticError("Posterior precision must be positive")

    # Posterior mean (weighted average of prior and data)
    if prior.is_proper():
        posterior_mean = (prior_precision * prior.mean + data_precision * effect_size) / posterior_precision
    else:
        # Non-informative prior: posterior = likelihood
        posterior_mean = effect_size

    # Posterior variance
    posterior_variance = 1.0 / posterior_precision

    return posterior_mean, posterior_variance


def chance_to_win(posterior_mean: float, posterior_std: float, inverse: bool = False) -> float:
    """
    Calculate probability that treatment outperforms control.

    For effect size θ, calculates P(θ > 0 | data) or P(θ < 0 | data).

    Args:
        posterior_mean: Posterior mean of effect size
        posterior_std: Posterior standard deviation of effect size
        inverse: If True, "lower is better" (calculate P(θ < 0))

    Returns:
        Probability between 0 and 1
    """
    if posterior_std <= 0:
        raise StatisticError("Posterior standard deviation must be positive")

    if inverse:
        # Lower is better
        return float(norm.cdf(0, loc=posterior_mean, scale=posterior_std))
    else:
        # Higher is better
        return float(norm.sf(0, loc=posterior_mean, scale=posterior_std))


def credible_interval(posterior_mean: float, posterior_std: float, alpha: float = 0.05) -> tuple[float, float]:
    """
    Calculate Bayesian credible interval.

    A credible interval gives the range that contains the true parameter
    with specified probability, based on the posterior distribution.
    Unlike frequentist confidence intervals, credible intervals can be
    interpreted as "there is a 95% probability the true value lies in this range."

    Args:
        posterior_mean: Posterior mean
        posterior_std: Posterior standard deviation
        alpha: Significance level (default: 0.05 for 95% credible interval)

    Returns:
        Tuple of (lower_bound, upper_bound)
    """
    if not (0 < alpha < 1):
        raise StatisticError("Alpha must be between 0 and 1")
    if posterior_std <= 0:
        raise StatisticError("Posterior standard deviation must be positive")

    return tuple(norm.ppf([alpha / 2, 1 - alpha / 2], loc=posterior_mean, scale=posterior_std))


def calculate_risk(posterior_mean: float, posterior_std: float) -> tuple[float, float]:
    """
    Calculate expected loss (risk) for each decision.

    Risk represents the expected loss if we make the wrong decision:
    - Risk of choosing control: E[θ | θ > 0] x P(θ > 0)
    - Risk of choosing treatment: E[|θ|] x P(θ < 0)]

    Args:
        posterior_mean: Posterior mean of effect size
        posterior_std: Posterior standard deviation

    Returns:
        Tuple of (risk_control, risk_treatment)
    """
    if posterior_std <= 0:
        raise StatisticError("Posterior standard deviation must be positive")

    # Probability that control is better (effect < 0)
    prob_control_better = norm.cdf(0, loc=posterior_mean, scale=posterior_std)

    # Probability that treatment is better (effect > 0)
    prob_treatment_better = 1 - prob_control_better

    # Expected effect given treatment is better (truncated normal mean for θ > 0)
    if prob_treatment_better > 1e-10:
        expected_effect_positive = truncated_normal_mean(posterior_mean, posterior_std, 0, np.inf)
    else:
        expected_effect_positive = 0

    # Expected absolute effect given control is better (truncated normal mean for θ < 0)
    if prob_control_better > 1e-10:
        expected_effect_negative = abs(truncated_normal_mean(posterior_mean, posterior_std, -np.inf, 0))
    else:
        expected_effect_negative = 0

    # Risk calculations
    risk_control = prob_treatment_better * expected_effect_positive
    risk_treatment = prob_control_better * expected_effect_negative

    return float(risk_control), float(risk_treatment)


def truncated_normal_mean(mu: float, sigma: float, a: float, b: float) -> float:
    """
    Calculate expected value of truncated normal distribution.

    For X ~ N(μ, σ²) truncated to [a, b], computes E[X | a ≤ X ≤ b].

    Args:
        mu: Original normal distribution mean
        sigma: Original normal distribution std dev
        a: Lower truncation bound (-np.inf for no lower bound)
        b: Upper truncation bound (np.inf for no upper bound)

    Returns:
        Expected value of truncated distribution
    """
    if sigma <= 0:
        raise StatisticError("Standard deviation must be positive")

    # Standardize bounds
    a_std = (a - mu) / sigma if not np.isinf(a) else a
    b_std = (b - mu) / sigma if not np.isinf(b) else b

    # Use scipy's truncated normal
    try:
        return float(truncnorm.mean(a_std, b_std, loc=mu, scale=sigma))
    except Exception as e:
        # Handle numerical issues
        if np.isfinite(a) and np.isfinite(b):
            return mu  # Fallback to original mean
        raise StatisticError(f"Failed to calculate truncated normal mean: {e}")


def validate_inputs(
    treatment_stat: Union[SampleMeanStatistic, ProportionStatistic],
    control_stat: Union[SampleMeanStatistic, ProportionStatistic],
) -> None:
    """
    Validate input statistics for Bayesian analysis.

    Args:
        treatment_stat: Treatment group statistic
        control_stat: Control group statistic

    Raises:
        StatisticError: If inputs are invalid
    """

    # Check that both are the same type
    if not isinstance(treatment_stat, type(control_stat)):
        raise StatisticError("Treatment and control statistics must be the same type")

    # Check sample sizes
    if get_sample_size(treatment_stat) <= 0:
        raise StatisticError("Treatment sample size must be positive")

    if get_sample_size(control_stat) <= 0:
        raise StatisticError("Control sample size must be positive")

    # Check variances
    if get_variance(treatment_stat) < 0:
        raise StatisticError("Treatment variance cannot be negative")

    if get_variance(control_stat) < 0:
        raise StatisticError("Control variance cannot be negative")
