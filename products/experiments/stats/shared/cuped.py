"""
CUPED (Controlled-experiment Using Pre-Experiment Data) variance reduction.

This module implements CUPED as a preprocessing step that transforms post-exposure
statistics into adjusted statistics with reduced variance. The adjusted statistics
are standard SampleMeanStatistic objects that can be fed directly into existing
Bayesian or Frequentist test methods.

Reference: Deng et al. 2013 - "Improving the Sensitivity of Online Controlled
Experiments by Utilizing Pre-Experiment Data"
"""

from dataclasses import dataclass

from .statistics import ProportionStatistic, RatioStatistic, SampleMeanStatistic, StatisticError

VARIANCE_FLOOR = 1e-10


@dataclass
class CupedData:
    """Pre-experiment covariate data for a single experimental group.

    Attributes:
        pre_statistic: Pre-exposure metric values as SampleMeanStatistic (n, sum, sum_squares).
            Even for binomial post-metrics, the pre-exposure covariate is continuous.
        sum_of_cross_products: Σ(post_i * pre_i) across users in this group,
            used to compute Cov(Y, X) between post and pre values.
    """

    pre_statistic: SampleMeanStatistic
    sum_of_cross_products: float


@dataclass
class CupedResult:
    """Result of CUPED adjustment with metadata for display.

    Attributes:
        treatment_adjusted: CUPED-adjusted treatment statistic.
        control_adjusted: CUPED-adjusted control statistic.
        theta: The regression coefficient used for adjustment.
        treatment_unadjusted_mean: Original treatment mean before adjustment.
        control_unadjusted_mean: Original control mean before adjustment.
        variance_reduction_treatment: Fraction of variance reduced (1 - adjusted/original).
        variance_reduction_control: Fraction of variance reduced (1 - adjusted/original).
    """

    treatment_adjusted: SampleMeanStatistic
    control_adjusted: SampleMeanStatistic
    theta: float
    treatment_unadjusted_mean: float
    control_unadjusted_mean: float
    variance_reduction_treatment: float
    variance_reduction_control: float


def _get_post_sum(post: SampleMeanStatistic | ProportionStatistic) -> float:
    """Get the sum from a post-exposure statistic regardless of type."""
    return float(post.sum)


def _get_post_mean(post: SampleMeanStatistic | ProportionStatistic) -> float:
    """Get the mean from a post-exposure statistic regardless of type."""
    if isinstance(post, ProportionStatistic):
        return post.proportion
    return post.mean


def _compute_covariance(
    n: int,
    post_sum: float,
    pre_sum: float,
    sum_of_cross_products: float,
) -> float:
    """Compute sample covariance between post and pre metrics.

    Uses Bessel's correction: Cov(Y, X) = [Σ(Y_i * X_i) - (ΣY_i * ΣX_i) / n] / (n - 1)
    """
    if n <= 1:
        return 0.0
    return (sum_of_cross_products - post_sum * pre_sum / n) / (n - 1)


def compute_theta(
    treatment_post: SampleMeanStatistic | ProportionStatistic,
    control_post: SampleMeanStatistic | ProportionStatistic,
    treatment_cuped: CupedData,
    control_cuped: CupedData,
) -> float:
    """Compute optimal theta by pooling treatment and control data.

    θ = Cov_pooled(Y, X) / Var_pooled(X)

    where Y is the post-exposure metric and X is the pre-exposure covariate,
    pooled across both experimental groups.

    Returns 0.0 if the pre-exposure variance is near zero (no adjustment possible).
    """
    n_all = treatment_post.n + control_post.n
    if n_all <= 1:
        return 0.0

    sum_cross_all = treatment_cuped.sum_of_cross_products + control_cuped.sum_of_cross_products
    sum_post_all = _get_post_sum(treatment_post) + _get_post_sum(control_post)
    sum_pre_all = treatment_cuped.pre_statistic.sum + control_cuped.pre_statistic.sum
    sum_squares_pre_all = treatment_cuped.pre_statistic.sum_squares + control_cuped.pre_statistic.sum_squares

    var_pre_pooled = (sum_squares_pre_all - sum_pre_all**2 / n_all) / (n_all - 1)
    if var_pre_pooled < VARIANCE_FLOOR:
        return 0.0

    cov_pooled = (sum_cross_all - sum_post_all * sum_pre_all / n_all) / (n_all - 1)
    return cov_pooled / var_pre_pooled


def _adjust_group(
    post: SampleMeanStatistic | ProportionStatistic,
    cuped: CupedData,
    theta: float,
) -> tuple[SampleMeanStatistic, float]:
    """Apply CUPED adjustment to a single group.

    Returns the adjusted SampleMeanStatistic and the variance reduction fraction.
    """
    n = post.n
    post_mean = _get_post_mean(post)
    post_variance = post.variance
    pre_mean = cuped.pre_statistic.mean
    pre_variance = cuped.pre_statistic.variance

    covariance = _compute_covariance(
        n=n,
        post_sum=_get_post_sum(post),
        pre_sum=cuped.pre_statistic.sum,
        sum_of_cross_products=cuped.sum_of_cross_products,
    )

    adjusted_mean = post_mean - theta * pre_mean
    adjusted_variance = post_variance + theta**2 * pre_variance - 2 * theta * covariance
    adjusted_variance = max(adjusted_variance, VARIANCE_FLOOR)

    variance_reduction = 1.0 - adjusted_variance / post_variance if post_variance > VARIANCE_FLOOR else 0.0

    # Construct synthetic SampleMeanStatistic from adjusted values:
    # sum = adjusted_mean * n
    # sum_squares = adjusted_variance * (n - 1) + sum^2 / n
    adj_sum = adjusted_mean * n
    adj_sum_squares = adjusted_variance * (n - 1) + adj_sum**2 / n if n > 1 else adj_sum**2

    adjusted_stat = SampleMeanStatistic(n=n, sum=adj_sum, sum_squares=adj_sum_squares)
    return adjusted_stat, variance_reduction


def cuped_adjust(
    treatment_post: SampleMeanStatistic | ProportionStatistic,
    control_post: SampleMeanStatistic | ProportionStatistic,
    treatment_cuped: CupedData,
    control_cuped: CupedData,
) -> CupedResult:
    """Apply CUPED variance reduction to experiment statistics.

    This is the main public API. It computes the optimal regression coefficient (theta)
    by pooling both groups, then adjusts each group's mean and variance. The result
    contains SampleMeanStatistic objects that can be passed directly to
    BayesianMethod.run_test() or FrequentistMethod.run_test().

    Args:
        treatment_post: Post-exposure treatment statistic.
        control_post: Post-exposure control statistic.
        treatment_cuped: Pre-exposure covariate data for treatment group.
        control_cuped: Pre-exposure covariate data for control group.

    Returns:
        CupedResult with adjusted statistics and metadata.

    Raises:
        StatisticError: If inputs are invalid (mismatched n, unsupported types).
    """
    if isinstance(treatment_post, RatioStatistic) or isinstance(control_post, RatioStatistic):
        raise StatisticError("CUPED adjustment for ratio metrics is not yet supported")

    if type(treatment_post) is not type(control_post):
        raise StatisticError("Treatment and control post-statistics must be the same type")

    if treatment_post.n != treatment_cuped.pre_statistic.n:
        raise StatisticError(
            f"Treatment post n ({treatment_post.n}) does not match pre n ({treatment_cuped.pre_statistic.n})"
        )
    if control_post.n != control_cuped.pre_statistic.n:
        raise StatisticError(
            f"Control post n ({control_post.n}) does not match pre n ({control_cuped.pre_statistic.n})"
        )

    treatment_unadjusted_mean = _get_post_mean(treatment_post)
    control_unadjusted_mean = _get_post_mean(control_post)

    theta = compute_theta(treatment_post, control_post, treatment_cuped, control_cuped)

    if theta == 0.0:
        treatment_adjusted, _ = _adjust_group(treatment_post, treatment_cuped, 0.0)
        control_adjusted, _ = _adjust_group(control_post, control_cuped, 0.0)
        return CupedResult(
            treatment_adjusted=treatment_adjusted,
            control_adjusted=control_adjusted,
            theta=0.0,
            treatment_unadjusted_mean=treatment_unadjusted_mean,
            control_unadjusted_mean=control_unadjusted_mean,
            variance_reduction_treatment=0.0,
            variance_reduction_control=0.0,
        )

    treatment_adjusted, vr_treatment = _adjust_group(treatment_post, treatment_cuped, theta)
    control_adjusted, vr_control = _adjust_group(control_post, control_cuped, theta)

    return CupedResult(
        treatment_adjusted=treatment_adjusted,
        control_adjusted=control_adjusted,
        theta=theta,
        treatment_unadjusted_mean=treatment_unadjusted_mean,
        control_unadjusted_mean=control_unadjusted_mean,
        variance_reduction_treatment=vr_treatment,
        variance_reduction_control=vr_control,
    )
