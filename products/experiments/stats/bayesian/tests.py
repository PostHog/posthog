"""
Bayesian test implementations for A/B testing.

This module provides Bayesian statistical test implementations that
output probabilistic results including chance to win, credible intervals,
and risk assessments.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Union
import numpy as np

from ..shared.statistics import (
    SampleMeanStatistic,
    ProportionStatistic,
    StatisticError,
)
from ..shared.enums import DifferenceType

from .priors import GaussianPrior
from .utils import (
    calculate_effect_size_and_variance,
    calculate_posterior,
    chance_to_win,
    credible_interval,
    calculate_risk,
    validate_inputs,
)


@dataclass
class BayesianResult:
    """
    Result of a Bayesian statistical test.

    Contains probabilistic outputs that are intuitive for business decision-making.
    """

    # Point estimates
    effect_size: float  # Posterior mean of effect size
    credible_interval: tuple[float, float]  # Bayesian credible interval

    # Probabilities
    chance_to_win: float  # P(treatment > control | data)

    # Risk assessment
    risk_control: float  # Expected loss if we choose control
    risk_treatment: float  # Expected loss if we choose treatment

    # Posterior distribution parameters
    posterior_variance: float  # Variance of posterior distribution

    # Configuration
    ci_level: float  # Credible interval level (0.95 for 95% CI)
    difference_type: str  # Type of difference calculated
    inverse: bool  # Whether "lower is better"

    # Prior information
    prior_mean: float  # Prior mean used
    prior_variance: float  # Prior variance used
    proper_prior: bool  # Whether informative prior was used

    @property
    def posterior_std(self) -> float:
        """Posterior standard deviation."""
        return np.sqrt(self.posterior_variance)

    @property
    def is_decisive(self) -> bool:
        """Whether result shows clear preference (chance to win > ci_level or < 1 - ci_level)."""
        return self.chance_to_win > self.ci_level or self.chance_to_win < 1 - self.ci_level

    @property
    def preferred_variation(self) -> str:
        """Which variation is preferred based on chance to win."""
        if self.chance_to_win > 0.5:
            return "treatment"
        else:
            return "control"

    @property
    def confidence_in_decision(self) -> float:
        """Confidence in the preferred variation."""
        return max(self.chance_to_win, 1 - self.chance_to_win)


class BayesianTest(ABC):
    """Abstract base class for Bayesian statistical tests."""

    def __init__(self, ci_level: float = 0.95, inverse: bool = False):
        """
        Initialize Bayesian test.

        Args:
            ci_level: Credible interval level (default: 0.95 for 95% intervals)
            inverse: Whether "lower is better" for this metric (default: False)
        """
        if not (0 < ci_level < 1):
            raise StatisticError("ci_level must be between 0 and 1")

        self.ci_level = ci_level
        self.inverse = inverse

    @property
    @abstractmethod
    def test_name(self) -> str:
        """Return the test name identifier."""
        pass

    @abstractmethod
    def run_test(
        self,
        treatment_stat: Union[SampleMeanStatistic, ProportionStatistic],
        control_stat: Union[SampleMeanStatistic, ProportionStatistic],
        prior: GaussianPrior,
        difference_type: DifferenceType = DifferenceType.RELATIVE,
        **kwargs,
    ) -> BayesianResult:
        """
        Run the Bayesian statistical test.

        Args:
            treatment_stat: Treatment group statistic
            control_stat: Control group statistic
            prior: Prior distribution for effect size
            difference_type: Type of difference to calculate
            **kwargs: Additional test-specific parameters

        Returns:
            BayesianResult object
        """
        pass


class BayesianGaussianTest(BayesianTest):
    """
    Bayesian test using Gaussian conjugate priors for effect sizes.

    Assumes the effect size follows a normal distribution and uses
    Gaussian conjugate priors to compute posterior distributions.

    Note: This is appropriate for large samples where the Central Limit
    Theorem ensures approximate normality of effect size estimates.
    """

    @property
    def test_name(self) -> str:
        return "bayesian_gaussian_test"

    def run_test(
        self,
        treatment_stat: Union[SampleMeanStatistic, ProportionStatistic],
        control_stat: Union[SampleMeanStatistic, ProportionStatistic],
        prior: GaussianPrior,
        difference_type: DifferenceType = DifferenceType.RELATIVE,
        **kwargs,
    ) -> BayesianResult:
        """
        Run Bayesian t-test comparing treatment vs control.

        Args:
            treatment_stat: Treatment group statistic
            control_stat: Control group statistic
            prior: Gaussian prior for effect size
            difference_type: Type of difference to calculate (relative/absolute)
            **kwargs: Additional parameters (currently unused)

        Returns:
            BayesianResult with all probabilistic outputs

        Raises:
            StatisticError: If inputs are invalid or calculations fail
        """
        # Validate inputs
        validate_inputs(treatment_stat, control_stat)

        if not isinstance(prior, GaussianPrior):
            raise StatisticError("Prior must be a GaussianPrior instance")

        if difference_type not in [DifferenceType.RELATIVE, DifferenceType.ABSOLUTE]:
            raise StatisticError("Only relative and absolute differences supported for Bayesian tests")

        try:
            # Calculate effect size and variance
            effect_size, effect_variance = calculate_effect_size_and_variance(
                treatment_stat, control_stat, difference_type
            )

            # Bayesian posterior update
            posterior_mean, posterior_variance = calculate_posterior(effect_size, effect_variance, prior)

            posterior_std = np.sqrt(posterior_variance)

            # Calculate probabilistic outputs
            chance_win = chance_to_win(posterior_mean, posterior_std, self.inverse)

            # Credible interval (convert ci_level to alpha for internal function)
            alpha = 1 - self.ci_level
            ci_lower, ci_upper = credible_interval(posterior_mean, posterior_std, alpha)

            # Risk assessment
            risk_control, risk_treatment = calculate_risk(posterior_mean, posterior_std)

            return BayesianResult(
                effect_size=posterior_mean,
                credible_interval=(ci_lower, ci_upper),
                chance_to_win=chance_win,
                risk_control=risk_control,
                risk_treatment=risk_treatment,
                posterior_variance=posterior_variance,
                ci_level=self.ci_level,
                difference_type=difference_type.value,
                inverse=self.inverse,
                prior_mean=prior.mean,
                prior_variance=prior.variance,
                proper_prior=prior.proper,
            )

        except StatisticError:
            # Re-raise StatisticError with original traceback
            raise
        except Exception as e:
            raise StatisticError(f"Bayesian test calculation failed: {str(e)}") from e


class BayesianProportionTest(BayesianTest):
    """
    Bayesian test for proportion/conversion rate metrics using Normal approximation.

    Uses a Gaussian approximation to the binomial distribution for effect size inference.
    This approximation is valid when np > 5 and n(1-p) > 5 for both groups.

    For exact Bayesian inference on proportions, a Beta-Binomial conjugate model
    would be more appropriate, but is not implemented in this version.
    """

    @property
    def test_name(self) -> str:
        return "bayesian_proportion_test"

    def run_test(
        self,
        treatment_stat: ProportionStatistic,
        control_stat: ProportionStatistic,
        prior: GaussianPrior,
        difference_type: DifferenceType = DifferenceType.RELATIVE,
        **kwargs,
    ) -> BayesianResult:
        """
        Run Bayesian test for proportion data using Normal approximation.

        Args:
            treatment_stat: Treatment group proportion statistic
            control_stat: Control group proportion statistic
            prior: Gaussian prior for effect size
            difference_type: Type of difference to calculate
            **kwargs: Additional parameters

        Returns:
            BayesianResult with proportion-specific interpretations

        Raises:
            StatisticError: If Normal approximation is not valid
        """
        # Validate proportion-specific inputs
        if not isinstance(treatment_stat, ProportionStatistic):
            raise StatisticError("Treatment statistic must be ProportionStatistic")

        if not isinstance(control_stat, ProportionStatistic):
            raise StatisticError("Control statistic must be ProportionStatistic")

        # Check Normal approximation validity
        self._validate_normal_approximation(treatment_stat, control_stat)

        # Use the general Bayesian Gaussian test implementation
        gaussian_test = BayesianGaussianTest(ci_level=self.ci_level, inverse=self.inverse)
        result = gaussian_test.run_test(treatment_stat, control_stat, prior, difference_type, **kwargs)

        # Update test type for result tracking
        result.difference_type = f"proportion_{difference_type.value}"

        return result

    def _validate_normal_approximation(
        self, treatment_stat: ProportionStatistic, control_stat: ProportionStatistic
    ) -> None:
        """
        Validate that Normal approximation to binomial is appropriate.

        Checks the rule of thumb: np > 5 and n(1-p) > 5 for both groups.
        """
        for name, stat in [("treatment", treatment_stat), ("control", control_stat)]:
            successes = stat.sum
            failures = stat.n - stat.sum

            if successes < 5:
                raise StatisticError(
                    f"Normal approximation invalid: {name} has only {successes} successes "
                    f"(need ≥5). Consider using exact binomial methods."
                )

            if failures < 5:
                raise StatisticError(
                    f"Normal approximation invalid: {name} has only {failures} failures "
                    f"(need ≥5). Consider using exact binomial methods."
                )


class BayesianMeanTest(BayesianTest):
    """
    Bayesian test for continuous mean metrics using Gaussian conjugate priors.

    This test is appropriate for continuous metrics where the effect size
    can be modeled as normally distributed. The Gaussian conjugate prior
    assumption is well-suited for means when sample sizes are large enough
    for the Central Limit Theorem to apply.
    """

    @property
    def test_name(self) -> str:
        return "bayesian_mean_test"

    def run_test(
        self,
        treatment_stat: SampleMeanStatistic,
        control_stat: SampleMeanStatistic,
        prior: GaussianPrior,
        difference_type: DifferenceType = DifferenceType.RELATIVE,
        **kwargs,
    ) -> BayesianResult:
        """
        Run Bayesian test for continuous mean data.

        Args:
            treatment_stat: Treatment group mean statistic
            control_stat: Control group mean statistic
            prior: Gaussian prior for effect size
            difference_type: Type of difference to calculate
            **kwargs: Additional parameters

        Returns:
            BayesianResult with mean-specific interpretations
        """
        # Validate mean-specific inputs
        if not isinstance(treatment_stat, SampleMeanStatistic):
            raise StatisticError("Treatment statistic must be SampleMeanStatistic")

        if not isinstance(control_stat, SampleMeanStatistic):
            raise StatisticError("Control statistic must be SampleMeanStatistic")

        # Use the general Bayesian Gaussian test implementation
        gaussian_test = BayesianGaussianTest(ci_level=self.ci_level, inverse=self.inverse)
        result = gaussian_test.run_test(treatment_stat, control_stat, prior, difference_type, **kwargs)

        # Update test type for result tracking
        result.difference_type = f"mean_{difference_type.value}"

        return result
