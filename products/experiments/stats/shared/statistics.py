from dataclasses import dataclass
import numpy as np


class StatisticError(Exception):
    """Base exception for statistic-related errors."""

    pass


class InvalidStatisticError(StatisticError):
    """Raised when statistic inputs are invalid."""

    pass


@dataclass
class SampleMeanStatistic:
    """
    Statistics for continuous metrics (e.g., revenue, session duration).

    For a sample of continuous values, this stores sufficient statistics
    to compute the sample mean and variance.
    """

    n: int  # Sample size (number of observations)
    sum: float  # Sum of all observations
    sum_squares: float  # Sum of squared observations

    def __post_init__(self):
        """Validate inputs and check mathematical constraints."""
        if self.n <= 0:
            raise InvalidStatisticError("Sample size must be positive")
        if self.n == 1 and self.sum_squares < self.sum**2:
            raise InvalidStatisticError("sum_squares must be >= sum^2 for single observation")
        if self.n > 1 and self.sum_squares < self.sum**2 / self.n:
            raise InvalidStatisticError("sum_squares incompatible with sum and n")

    @property
    def mean(self) -> float:
        """Sample mean: μ = sum / n"""
        return self.sum / self.n

    @property
    def variance(self) -> float:
        """Sample variance: s² = (sum_squares - sum²/n) / (n-1)"""
        if self.n == 1:
            return 0.0
        return (self.sum_squares - self.sum**2 / self.n) / (self.n - 1)

    @property
    def standard_error(self) -> float:
        """Standard error of the mean: SE = √(s²/n)"""
        return np.sqrt(self.variance / self.n)


@dataclass
class ProportionStatistic:
    """
    Statistics for binary/conversion metrics (e.g., conversion rate, CTR).

    For a sample of binary outcomes (success/failure), this stores
    the number of trials and successes.
    """

    n: int  # Sample size (number of users/units exposed)
    sum: int  # Number of successes/conversions

    def __post_init__(self):
        """Validate inputs."""
        if self.n <= 0:
            raise InvalidStatisticError("Sample size must be positive")
        if self.sum < 0:
            raise InvalidStatisticError("Number of successes cannot be negative")
        if self.sum > self.n:
            raise InvalidStatisticError("Number of successes cannot exceed sample size")

    @property
    def proportion(self) -> float:
        """Sample proportion: p = sum / n"""
        return self.sum / self.n

    @property
    def variance(self) -> float:
        """Binomial variance: Var(p) = p(1-p)"""
        p = self.proportion
        return p * (1 - p)

    @property
    def standard_error(self) -> float:
        """Standard error of proportion: SE = √(p(1-p)/n)"""
        return np.sqrt(self.variance / self.n)


# Type alias for any statistic type
AnyStatistic = SampleMeanStatistic | ProportionStatistic
