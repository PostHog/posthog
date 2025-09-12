from dataclasses import dataclass

import numpy as np


class StatisticError(ValueError):
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


@dataclass
class RatioStatistic:
    """
    Statistics for ratio metrics (e.g., revenue per order, clicks per session).

    Uses the delta method for variance approximation of ratios.
    """

    n: int  # Sample size
    m_statistic: SampleMeanStatistic | ProportionStatistic  # Numerator statistic
    d_statistic: SampleMeanStatistic | ProportionStatistic  # Denominator statistic
    m_d_sum_of_products: float  # Sum of products between numerator and denominator

    def __post_init__(self):
        """Validate inputs."""
        if self.n <= 0:
            raise InvalidStatisticError("Sample size must be positive")
        if self.m_statistic.n != self.n or self.d_statistic.n != self.n:
            raise InvalidStatisticError("All statistics must have same sample size")
        d_mean = self.d_statistic.mean if hasattr(self.d_statistic, "mean") else self.d_statistic.proportion
        if abs(d_mean) < 1e-10:
            raise InvalidStatisticError("Denominator mean cannot be zero for ratio calculation")

    @property
    def ratio(self) -> float:
        """Ratio estimate: R = Σm / Σd"""
        m_sum = self.m_statistic.sum
        d_sum = self.d_statistic.sum
        return m_sum / d_sum

    @property
    def covariance(self) -> float:
        """Sample covariance: Cov(M,D) = (sum_products - sum_m × sum_d / n) / (n-1)"""
        if self.n == 1:
            return 0.0
        m_sum = self.m_statistic.sum
        d_sum = self.d_statistic.sum
        return (self.m_d_sum_of_products - m_sum * d_sum / self.n) / (self.n - 1)

    @property
    def variance(self) -> float:
        """Delta method variance for ratio R = M/D"""
        m_mean = self.m_statistic.mean if hasattr(self.m_statistic, "mean") else self.m_statistic.proportion
        d_mean = self.d_statistic.mean if hasattr(self.d_statistic, "mean") else self.d_statistic.proportion
        m_var = self.m_statistic.variance
        d_var = self.d_statistic.variance
        cov = self.covariance

        # Delta method: Var(R) ≈ Var(M)/D² + M²Var(D)/D⁴ - 2M*Cov(M,D)/D³
        return m_var / d_mean**2 + m_mean**2 * d_var / d_mean**4 - 2 * m_mean * cov / d_mean**3

    @property
    def standard_error(self) -> float:
        """Standard error of the ratio: SE = √(Var(R)/n)"""
        return np.sqrt(self.variance / self.n)


# Type alias for any statistic type
AnyStatistic = SampleMeanStatistic | ProportionStatistic | RatioStatistic
