"""
Main BayesianMethod class for A/B testing.

This module provides the primary API for running Bayesian statistical
tests on A/B experiment data, with support for various prior configurations
and difference types.
"""

from dataclasses import dataclass
from typing import Optional

from ..shared.enums import DifferenceType
from ..shared.statistics import ProportionStatistic, RatioStatistic, SampleMeanStatistic, StatisticError
from .priors import GaussianPrior
from .tests import BayesianGaussianTest, BayesianMeanTest, BayesianProportionTest, BayesianResult, BayesianTest


@dataclass(frozen=True)
class BayesianConfig:
    """Configuration for Bayesian testing."""

    # Test configuration
    ci_level: float = 0.95  # Credible interval level (0.95 for 95% CI)
    inverse: bool = False  # Whether "lower is better" for this metric
    difference_type: DifferenceType = DifferenceType.RELATIVE

    # Prior configuration
    prior_mean: float = 0.0  # Prior belief about effect size
    prior_variance: float = 1.0  # Uncertainty in prior belief
    proper_prior: bool = False  # Whether to use informative prior

    def __post_init__(self):
        """Validate configuration parameters."""
        if not (0 < self.ci_level < 1):
            raise StatisticError("ci_level must be between 0 and 1")

        if self.prior_variance <= 0:
            raise StatisticError("Prior variance must be positive")

        if self.difference_type not in [
            DifferenceType.RELATIVE,
            DifferenceType.ABSOLUTE,
        ]:
            raise StatisticError("Only relative and absolute differences supported for Bayesian tests")

    def create_prior(self) -> GaussianPrior:
        """Create GaussianPrior from configuration."""
        return GaussianPrior(mean=self.prior_mean, variance=self.prior_variance, proper=self.proper_prior)


class BayesianMethod:
    """
    Main class for Bayesian A/B testing.

    This class provides a high-level interface for running Bayesian statistical tests
    on A/B experiment data with various prior configurations and difference types.

    Example:
        # Basic usage with non-informative prior
        method = BayesianMethod()
        result = method.run_test(treatment_stat, control_stat)

        # With informative prior for 5% expected increase
        config = BayesianConfig(
            prior_mean=0.05,
            prior_variance=0.01,
            proper_prior=True,
            difference_type=DifferenceType.RELATIVE
        )
        method = BayesianMethod(config)
        result = method.run_test(treatment_stat, control_stat)

        # Check results
        print(f"Chance to win: {result.chance_to_win:.1%}")
        print(f"Effect size: {result.effect_size:.3f}")
        print(f"Credible interval: {result.credible_interval}")
    """

    def __init__(self, config: Optional[BayesianConfig] = None):
        """
        Initialize BayesianMethod with configuration.

        Args:
            config: Configuration object (uses defaults if None)
        """
        self.config = config or BayesianConfig()

    def _get_test_instance(self, stat_type: type) -> BayesianTest:
        """
        Get or create test instance based on statistic type and configuration.

        Args:
            stat_type: Type of statistic (SampleMeanStatistic or ProportionStatistic)

        Returns:
            Appropriate BayesianTest instance
        """
        test: BayesianTest

        if stat_type == SampleMeanStatistic:
            test = BayesianMeanTest(ci_level=self.config.ci_level, inverse=self.config.inverse)
        elif stat_type == ProportionStatistic:
            test = BayesianProportionTest(ci_level=self.config.ci_level, inverse=self.config.inverse)
        else:
            # Fallback to general test
            test = BayesianGaussianTest(ci_level=self.config.ci_level, inverse=self.config.inverse)

        return test

    def run_test(
        self,
        treatment_stat: SampleMeanStatistic | ProportionStatistic | RatioStatistic,
        control_stat: SampleMeanStatistic | ProportionStatistic | RatioStatistic,
        prior: GaussianPrior | None = None,
        **kwargs,
    ) -> BayesianResult:
        """
        Run Bayesian statistical test comparing treatment vs control.

        Args:
            treatment_stat: Treatment group statistic
            control_stat: Control group statistic
            prior: Prior distribution (uses config if None)
            **kwargs: Additional parameters (overrides config values)

        Returns:
            BayesianResult with all probabilistic outputs

        Raises:
            StatisticError: If inputs are invalid or test fails
        """
        # Validate inputs are same type
        if not isinstance(treatment_stat, type(control_stat)):
            raise StatisticError("Treatment and control statistics must be the same type")

        # Get or create prior
        if prior is None:
            prior = self.config.create_prior()

        test = self._get_test_instance(type(treatment_stat))

        # Prepare difference type (allow override)
        difference_type = kwargs.pop("difference_type", self.config.difference_type)

        try:
            return test.run_test(
                treatment_stat=treatment_stat,
                control_stat=control_stat,
                prior=prior,
                difference_type=difference_type,
                **kwargs,
            )
        except Exception as e:
            raise StatisticError(f"Bayesian test execution failed: {str(e)}") from e
