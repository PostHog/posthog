import math
from dataclasses import dataclass

import numpy as np

from posthog.dataclasses import frozen


class StatisticError(ValueError):
    """Base exception for statistic-related errors."""

    pass


class InvalidStatisticError(StatisticError):
    """Raised when statistic inputs are invalid."""

    pass


@frozen
class RelativeEffectBaseline:
    """The mean that relative effects divide by, with its variance and its covariance with the treatment-control
    difference. Moments are on the scale of sample means, not individual observations."""

    mean: float
    variance: float
    # The adjusted difference contains control observations, so it covaries with the raw baseline.
    difference_covariance: float


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


# Normal 0.975 quantile. The quantile variance uses it to turn an interval half-width
# back into a standard error, so it cancels out and must not follow the experiment's alpha.
Z_975 = 1.959963984540054

# Reference sample sizes n* for the quantile interval. Query quantile levels must be
# constants, but n is only known after the query runs, so the query returns bounds for
# every grid size and choose_quantile_bounds picks one afterwards.
QUANTILE_N_STAR_GRID = [100 * 2**k for k in range(20)]

# The clustered variance estimates the spread between users. When the events come from fewer effective users
# than this, that estimate is often too small, and a test rejects a true null hypothesis too often.
QUANTILE_MIN_EFFECTIVE_CLUSTERS = 50


@dataclass(frozen=True, kw_only=True)
class QuantileGridLevel:
    """Probability levels of the outer quantile interval at one grid size n*."""

    n_star: int
    lower_level: float
    upper_level: float


@dataclass(frozen=True, kw_only=True)
class QuantileBounds:
    """Observed values Y_L and Y_U at the probability levels of one grid size n*."""

    n_star: int
    lower: float
    upper: float


def quantile_grid_levels(nu: float) -> list[QuantileGridLevel]:
    """
    Probability levels L and U of the outer interval around quantile level nu, one per grid size.

    L and U are nu -/+ Z_975 * sqrt(nu(1-nu)/n*), clipped to (0, 1) and rounded to 10 decimals
    so that the query text is stable.
    """
    levels = []
    for n_star in QUANTILE_N_STAR_GRID:
        se_p = math.sqrt(nu * (1 - nu) / n_star)
        lower = round(max(nu - Z_975 * se_p, 1e-8), 10)
        upper = round(min(nu + Z_975 * se_p, 1 - 1e-8), 10)
        levels.append(QuantileGridLevel(n_star=n_star, lower_level=lower, upper_level=upper))
    return levels


def choose_quantile_bounds(n: int, bounds: list[QuantileBounds]) -> QuantileBounds | None:
    """
    Choose the bounds to use for a variant with n events.

    bounds is in grid order. Picks the largest n* <= n, or the smallest grid size when n is
    below it. Steps down to smaller n* while Y_L == Y_U (tied values).
    Returns None when all eligible bounds collapse.
    """
    eligible = [b for b in bounds if b.n_star <= n] or [bounds[0]]
    for candidate in reversed(eligible):
        if candidate.upper > candidate.lower:
            return candidate
    return None


@dataclass(frozen=True)
class QuantileStatistic:
    """
    Statistics for event-level quantile metrics (e.g., p90 of page load time over all events).

    The quantile is taken over all events of the variant, pooled across users. Users are the
    randomization unit, so the variance is clustered by user with the delta method from
    Deng, Knoblich and Lu (2018), "Applying the Delta Method in Metric Analytics".

    n is the number of events, and variance is per event, so variance / n is the variance
    of the quantile estimate.
    """

    nu: float  # Quantile level, 0 < nu < 1
    n: int  # Number of qualifying events
    n_clusters: int  # Exposed users K, including users without events
    quantile: float  # Empirical nu-quantile of all event values
    quantile_lower: float  # Y_L at the chosen n*
    quantile_upper: float  # Y_U at the chosen n*
    n_star: int  # Chosen n* from QUANTILE_N_STAR_GRID
    s_sum: float  # Σ S_i, where S_i is the number of events of user i with value <= quantile
    s_sum_squares: float  # Σ S_i²
    n_sum: float  # Σ N_i, where N_i is the number of events of user i (equals n)
    n_sum_squares: float  # Σ N_i²
    s_n_sum_of_products: float  # Σ S_i·N_i

    def __post_init__(self):
        """Validate inputs."""
        if not (0 < self.nu < 1):
            raise InvalidStatisticError("Quantile level must be between 0 and 1")
        if self.n <= 0:
            raise InvalidStatisticError("Sample size must be positive")
        if self.n_clusters <= 0:
            raise InvalidStatisticError("Number of clusters must be positive")
        if self.n_star <= 0:
            raise InvalidStatisticError("Reference sample size must be positive")
        if self.n_sum != self.n:
            raise InvalidStatisticError(
                "n_sum (Σ N_i, the total events over all users) must equal n (the number of events)"
            )
        if self.s_sum < 0 or self.s_sum > self.n_sum:
            raise InvalidStatisticError("Events below the quantile must be between 0 and sample size")
        if self.quantile_lower > self.quantile_upper:
            raise InvalidStatisticError("Lower quantile bound cannot exceed upper quantile bound")

    @property
    def mean(self) -> float:
        """Central value: the empirical quantile"""
        return self.quantile

    @property
    def iid_variance(self) -> float:
        """Per-event variance of the quantile if events were iid: (n*/n)(n-1)((Y_U - Y_L) / 2z)²"""
        if self.n <= 1:
            return 0.0
        width = (self.quantile_upper - self.quantile_lower) / (2 * Z_975)
        return (self.n_star / self.n) * (self.n - 1) * width**2

    @property
    def cdf_cluster_variance(self) -> float:
        """Delta method variance of the empirical CDF at the quantile, Σ S_i / Σ N_i, over K users"""
        k = self.n_clusters
        if self.n <= 1 or self.nu == 0 or k <= 1 or self.n_sum <= 0:
            return 0.0
        mu_s = self.s_sum / k
        mu_n = self.n_sum / k
        var_s = (self.s_sum_squares / k - mu_s**2) * k / (k - 1)
        var_n = (self.n_sum_squares / k - mu_n**2) * k / (k - 1)
        cov_sn = (self.s_n_sum_of_products / k - mu_s * mu_n) * k / (k - 1)
        return (var_s - 2 * mu_s * cov_sn / mu_n + mu_s**2 * var_n / mu_n**2) / (k * mu_n**2)

    @property
    def unfloored_variance(self) -> float:
        """Clustered per-event variance: iid variance times the design effect of the CDF"""
        cdf_iid_variance = self.nu * (1 - self.nu) / self.n if self.n > 0 else 0.0
        if cdf_iid_variance <= 0:
            return 0.0
        return self.iid_variance * self.cdf_cluster_variance / cdf_iid_variance

    @property
    def variance(self) -> float:
        """Clustered per-event variance, floored at 1e-5 when n >= 100"""
        variance = self.unfloored_variance
        return max(variance, 1e-5) if self.n >= 100 else variance

    @property
    def has_zero_variance(self) -> bool:
        """True when the outer interval leaves [0, 1] or the variance is not positive"""
        z2 = Z_975**2
        if self.n <= z2 * self.nu / (1 - self.nu) or self.n <= z2 * (1 - self.nu) / self.nu:
            return True
        # The floor in variance turns collapsed bounds (Y_L == Y_U) into 1e-5, so read the value before it.
        return self.unfloored_variance <= 0

    @property
    def has_tied_bound(self) -> bool:
        """
        True when the quantile equals Y_L or Y_U.

        Events tied at the quantile value then fill one side of the outer interval, so Y_U - Y_L
        measures the gap between tied values instead of the sampling spread of the quantile.
        """
        return self.quantile in (self.quantile_lower, self.quantile_upper)

    @property
    def effective_clusters(self) -> float:
        """Effective number of users when each user counts with its events: (Σ N_i)² / Σ N_i²"""
        return self.n_sum**2 / self.n_sum_squares if self.n_sum_squares > 0 else 0.0

    @property
    def has_few_effective_clusters(self) -> bool:
        """True when a few users produce so many of the events that the clustered variance is unreliable"""
        return self.effective_clusters < QUANTILE_MIN_EFFECTIVE_CLUSTERS

    @property
    def standard_error(self) -> float:
        """Standard error of the quantile: SE = √(variance/n)"""
        return float(np.sqrt(self.variance / self.n))


# Type alias for any statistic type
AnyStatistic = SampleMeanStatistic | ProportionStatistic | RatioStatistic | QuantileStatistic
