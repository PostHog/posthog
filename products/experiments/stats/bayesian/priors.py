"""
Prior distribution classes for Bayesian A/B testing.

This module defines prior distributions used in Bayesian inference,
focusing on Gaussian priors for effect sizes.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GaussianPrior:
    """
    Gaussian prior distribution for effect sizes.

    Used to encode prior beliefs about the expected effect size
    and uncertainty in that belief.

    Attributes:
        mean: Prior belief about effect size (default: 0 - no effect expected)
        variance: Uncertainty in prior belief (default: 1 - moderately uncertain)
        proper: Whether to use informative prior (default: False - non-informative)
    """

    mean: float = 0.0
    variance: float = 1.0
    proper: bool = False

    def __post_init__(self):
        """Validate prior parameters."""
        if self.variance <= 0:
            raise ValueError("Prior variance must be positive")

    @property
    def precision(self) -> float:
        """Prior precision (1/variance). Returns 0 for non-informative priors."""
        if not self.proper:
            return 0.0
        return 1.0 / self.variance

    def is_proper(self) -> bool:
        """
        Check if this is a proper (informative) prior.

        Returns:
            True if the prior should influence the posterior, False for flat priors
        """
        return self.proper

    def __str__(self) -> str:
        """String representation of the prior."""
        if not self.is_proper():
            return "Non-informative prior"
        return f"N(μ={self.mean:.3f}, σ²={self.variance:.3f})"
