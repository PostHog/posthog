"""
Main BayesianMethod class for A/B testing.

This module provides the primary API for running Bayesian statistical
tests on A/B experiment data, with support for various prior configurations
and difference types.
"""

from dataclasses import dataclass
from typing import Optional, Any, Union

from ..shared.enums import DifferenceType
from ..shared.statistics import (
    SampleMeanStatistic,
    ProportionStatistic,
    StatisticError,
)
from .priors import GaussianPrior
from .enums import PriorType
from .tests import (
    BayesianResult,
    BayesianTest,
    BayesianGaussianTest,
    BayesianProportionTest,
    BayesianMeanTest,
)


@dataclass
class BayesianConfig:
    """Configuration for Bayesian testing."""

    # Test configuration
    ci_level: float = 0.95  # Credible interval level (0.95 for 95% CI)
    inverse: bool = False  # Whether "lower is better" for this metric
    difference_type: DifferenceType = DifferenceType.RELATIVE

    # Prior configuration
    prior_type: PriorType = PriorType.RELATIVE
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
        treatment_stat: Union[SampleMeanStatistic, ProportionStatistic],
        control_stat: Union[SampleMeanStatistic, ProportionStatistic],
        prior: Optional[GaussianPrior] = None,
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

    def get_summary(self, result: BayesianResult) -> dict[str, Any]:
        """
        Get human-readable summary of Bayesian test result.

        Args:
            result: BayesianResult object

        Returns:
            Dict with summary information
        """
        summary = {
            "preferred_variation": result.preferred_variation,
            "chance_to_win": result.chance_to_win,
            "confidence_in_decision": result.confidence_in_decision,
            "effect_size": result.effect_size,
            "credible_interval": result.credible_interval,
            "is_decisive": result.is_decisive,
            "difference_type": result.difference_type,
            "ci_level": result.ci_level,
        }

        # Add effect size interpretation
        if "relative" in result.difference_type:
            summary["interpretation"] = {
                "effect_size": f"{result.effect_size:.1%}",
                "effect_direction": "positive" if result.effect_size > 0 else "negative",
                "magnitude": self._interpret_effect_magnitude(abs(result.effect_size)),
            }
        else:  # absolute
            summary["interpretation"] = {
                "effect_size": result.effect_size,
                "effect_direction": "positive" if result.effect_size > 0 else "negative",
            }

        # Add risk assessment
        summary["risk_assessment"] = {
            "risk_choosing_control": result.risk_control,
            "risk_choosing_treatment": result.risk_treatment,
            "safer_choice": "control" if result.risk_control < result.risk_treatment else "treatment",
        }

        # Add prior information
        summary["prior_info"] = {
            "prior_mean": result.prior_mean,
            "prior_variance": result.prior_variance,
            "informative_prior": result.proper_prior,
        }

        # Add decision recommendation
        summary["recommendation"] = self._make_recommendation(result)

        return summary

    def _interpret_effect_magnitude(self, abs_effect: float) -> str:
        """Interpret the magnitude of a relative effect size."""
        if abs_effect < 0.01:
            return "negligible"
        elif abs_effect < 0.05:
            return "small"
        elif abs_effect < 0.15:
            return "moderate"
        elif abs_effect < 0.30:
            return "large"
        else:
            return "very_large"

    def _make_recommendation(self, result: BayesianResult) -> str:
        """Make a business recommendation based on the test result."""
        chance_to_win = result.chance_to_win
        preferred_variation = result.preferred_variation

        if chance_to_win > 0.95:
            return f"Strong evidence for {preferred_variation}. Safe to proceed."
        elif chance_to_win > 0.85:
            return f"Good evidence for {preferred_variation}. Consider proceeding with monitoring."
        elif chance_to_win > 0.65:
            return f"Weak evidence for {preferred_variation}. Consider collecting more data."
        else:
            return "Inconclusive evidence. Collect more data before making a decision."

    @classmethod
    def create_simple_config(
        cls,
        ci_level: float = 0.95,
        inverse: bool = False,
        difference_type: str = "relative",
        prior_mean: float = 0.0,
        prior_variance: float = 1.0,
        proper_prior: bool = False,
    ) -> BayesianConfig:
        """
        Create a simple configuration with basic parameters.

        Args:
            ci_level: Credible interval level (default: 0.95 for 95% CI)
            inverse: Whether "lower is better" (default: False)
            difference_type: Difference type string (default: "relative")
            prior_mean: Prior belief about effect size (default: 0.0)
            prior_variance: Prior uncertainty (default: 1.0)
            proper_prior: Whether to use informative prior (default: False)

        Returns:
            BayesianConfig object
        """
        # Convert string difference type
        difference_type_map = {
            "relative": DifferenceType.RELATIVE,
            "absolute": DifferenceType.ABSOLUTE,
        }

        if difference_type not in difference_type_map:
            raise StatisticError(f"Unknown difference type: {difference_type}")

        return BayesianConfig(
            ci_level=ci_level,
            inverse=inverse,
            difference_type=difference_type_map[difference_type],
            prior_mean=prior_mean,
            prior_variance=prior_variance,
            proper_prior=proper_prior,
        )
