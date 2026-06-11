import numpy as np
from scipy import stats

from products.experiments.stats.shared.enums import DifferenceType
from products.experiments.stats.shared.utils import get_mean, get_sample_size, get_variance

from ..shared.statistics import AnyStatistic, ProportionStatistic, StatisticError


def calculate_point_estimate(
    treatment_stat: AnyStatistic,
    control_stat: AnyStatistic,
    difference_type: DifferenceType,
    unadjusted_mean: float | None = None,
) -> float:
    """
    Calculate point estimate for treatment vs control comparison.

    Args:
        treatment_stat: Treatment group statistic
        control_stat: Control group statistic
        difference_type: Type of difference to calculate
        unadjusted_mean: Optional override for the denominator in relative calculations.
            When provided, used instead of the control mean. This is useful for CUPED
            where the adjusted control mean differs from the original control mean.

    Returns:
        Point estimate value

    Raises:
        StatisticError: If control mean is zero for relative calculations
    """
    treatment_mean = get_mean(treatment_stat)
    control_mean = get_mean(control_stat)

    if difference_type == DifferenceType.ABSOLUTE:
        return treatment_mean - control_mean

    elif difference_type == DifferenceType.RELATIVE:
        denominator = unadjusted_mean if unadjusted_mean is not None else control_mean
        if abs(denominator) < 1e-10:
            raise StatisticError("Control mean cannot be zero for relative difference calculation")
        return (treatment_mean - control_mean) / denominator

    else:
        raise StatisticError(f"Unknown difference type: {difference_type}")


def calculate_variance_pooled(
    treatment_stat: AnyStatistic,
    control_stat: AnyStatistic,
    difference_type: DifferenceType,
    unadjusted_mean: float | None = None,
) -> float:
    """
    Calculate pooled variance for treatment vs control comparison.

    For absolute differences: Var = Var_T/n_T + Var_C/n_C
    For relative differences: Uses delta method approximation

    Args:
        treatment_stat: Treatment group statistic
        control_stat: Control group statistic
        difference_type: Type of difference calculation
        unadjusted_mean: Optional override for the denominator in relative calculations.
            When provided, used instead of the control mean. This is useful for CUPED
            where the adjusted control mean differs from the original control mean.

    Returns:
        Pooled variance estimate
    """
    treatment_var = get_variance(treatment_stat)
    control_var = get_variance(control_stat)
    treatment_n = get_sample_size(treatment_stat)
    control_n = get_sample_size(control_stat)

    if difference_type == DifferenceType.ABSOLUTE:
        return treatment_var / treatment_n + control_var / control_n

    elif difference_type == DifferenceType.RELATIVE:
        # Delta method for relative differences
        treatment_mean = get_mean(treatment_stat)
        control_mean = get_mean(control_stat)
        denominator = unadjusted_mean if unadjusted_mean is not None else control_mean

        if abs(denominator) < 1e-10:
            raise StatisticError("Control mean cannot be zero for relative variance calculation")

        # Var(Y/X) ≈ Var(Y)/X² + Y²Var(X)/X⁴ - 2Y*Cov(X,Y)/X³
        # Since treatment and control are independent, Cov(X,Y) = 0
        var_y_over_x_squared = treatment_var / (treatment_n * denominator**2)
        y_squared_var_x_over_x_fourth = (treatment_mean**2 * control_var) / (control_n * denominator**4)

        return var_y_over_x_squared + y_squared_var_x_over_x_fourth

    else:
        raise StatisticError(f"Unknown difference type: {difference_type}")


def calculate_welch_satterthwaite_df(treatment_stat: AnyStatistic, control_stat: AnyStatistic) -> float:
    """
    Calculate degrees of freedom using Welch-Satterthwaite approximation.

    Formula: df = (s₁²/n₁ + s₂²/n₂)² / [(s₁²/n₁)²/(n₁-1) + (s₂²/n₂)²/(n₂-1)]

    Args:
        treatment_stat: Treatment group statistic
        control_stat: Control group statistic

    Returns:
        Degrees of freedom (may be fractional)
    """
    treatment_var = get_variance(treatment_stat)
    control_var = get_variance(control_stat)
    treatment_n = get_sample_size(treatment_stat)
    control_n = get_sample_size(control_stat)

    if min(treatment_n, control_n) < 2:
        raise StatisticError("Welch-Satterthwaite requires n ≥ 2 per group.")

    # Variance terms
    var1_over_n1 = treatment_var / treatment_n
    var2_over_n2 = control_var / control_n

    # Numerator: (s₁²/n₁ + s₂²/n₂)²
    numerator = (var1_over_n1 + var2_over_n2) ** 2

    # Denominator: (s₁²/n₁)²/(n₁-1) + (s₂²/n₂)²/(n₂-1)
    term1 = var1_over_n1**2 / (treatment_n - 1)
    term2 = var2_over_n2**2 / (control_n - 1)
    denominator = term1 + term2

    return numerator / denominator


def calculate_t_statistic(point_estimate: float, pooled_variance: float, null_hypothesis_value: float = 0.0) -> float:
    """
    Calculate t-statistic for hypothesis test.

    Formula: t = (point_estimate - H₀_value) / √variance

    Args:
        point_estimate: Estimated difference between groups
        pooled_variance: Pooled variance estimate
        null_hypothesis_value: Value under null hypothesis (default: 0)

    Returns:
        T-statistic value
    """
    if pooled_variance <= 0:
        raise StatisticError("Pooled variance must be positive")

    return (point_estimate - null_hypothesis_value) / np.sqrt(pooled_variance)


def calculate_p_value(t_statistic: float, degrees_of_freedom: float, test_type: str = "two_sided") -> float:
    """
    Calculate p-value for t-test.

    Args:
        t_statistic: Calculated t-statistic
        degrees_of_freedom: Degrees of freedom
        test_type: Type of test ("two_sided", "greater", "less")

    Returns:
        P-value
    """
    if test_type == "two_sided":
        return float(2 * (1 - stats.t.cdf(abs(t_statistic), degrees_of_freedom)))
    elif test_type == "greater":
        return float(1 - stats.t.cdf(t_statistic, degrees_of_freedom))
    elif test_type == "less":
        return float(stats.t.cdf(t_statistic, degrees_of_freedom))
    else:
        raise StatisticError(f"Unknown test type: {test_type}")


def calculate_confidence_interval(
    point_estimate: float,
    pooled_variance: float,
    degrees_of_freedom: float,
    alpha: float = 0.05,
    test_type: str = "two_sided",
) -> tuple[float, float]:
    """
    Calculate confidence interval for the point estimate.

    Args:
        point_estimate: Estimated difference between groups
        pooled_variance: Pooled variance estimate
        degrees_of_freedom: Degrees of freedom
        alpha: Significance level (default: 0.05)
        test_type: Type of test for interval bounds

    Returns:
        Tuple of (lower_bound, upper_bound)
    """
    if pooled_variance <= 0:
        raise StatisticError("Pooled variance must be positive")

    standard_error = np.sqrt(pooled_variance)

    if test_type == "two_sided":
        t_critical = stats.t.ppf(1 - alpha / 2, degrees_of_freedom)
        margin = t_critical * standard_error
        return (float(point_estimate - margin), float(point_estimate + margin))

    else:
        raise StatisticError(f"Unknown test type: {test_type}")


def validate_sample_sizes(treatment_stat: AnyStatistic, control_stat: AnyStatistic, min_sample_size: int = 5) -> None:
    """
    Validate that sample sizes meet minimum requirements.

    Args:
        treatment_stat: Treatment group statistic
        control_stat: Control group statistic
        min_sample_size: Minimum required sample size

    Raises:
        StatisticError: If sample sizes are too small
    """
    treatment_n = get_sample_size(treatment_stat)
    control_n = get_sample_size(control_stat)

    if treatment_n < min_sample_size:
        raise StatisticError(f"Treatment sample size ({treatment_n}) below minimum ({min_sample_size})")
    if control_n < min_sample_size:
        raise StatisticError(f"Control sample size ({control_n}) below minimum ({min_sample_size})")


def sequential_rho(alpha: float, sequential_tuning_parameter: float) -> float:
    """
    Convert the sequential testing tuning parameter `N` into the mixing parameter `rho`.

    Implements eq. 161 of Waudby-Smith et al. 2023 (two-sided form):
        rho = sqrt( ( -2*ln(alpha) + ln(-2*ln(alpha) + 1) ) / N )

    Args:
        alpha: Significance level (must be in (0, 1)).
        sequential_tuning_parameter: Positive number `N` controlling where along the
            data-collection timeline the confidence sequence is tightest.

    Returns:
        The mixing parameter rho.
    """
    if not (0 < alpha < 1):
        raise StatisticError("Alpha must be between 0 and 1")
    if sequential_tuning_parameter <= 0:
        raise StatisticError("Sequential tuning parameter must be positive")

    log_alpha = np.log(alpha)
    return float(np.sqrt((-2 * log_alpha + np.log(-2 * log_alpha + 1)) / sequential_tuning_parameter))


def sequential_interval_halfwidth(
    s2: float,
    n: int,
    sequential_tuning_parameter: float,
    alpha: float,
    rho: float | None = None,
) -> float:
    """
    Half-width of the two-sided always-valid confidence sequence.

    Implements eq. 9 of Waudby-Smith et al. 2023:
        halfwidth = sqrt(s2) * sqrt( 2*(n*rho^2 + 1) * ln(sqrt(n*rho^2 + 1)/alpha) / (n*rho)^2 )

    `s2` here is the per-observation variance (matching the paper's notation), NOT the
    variance of the estimator. For a two-sample test where the caller has
    SE^2 = Var_T/n_T + Var_C/n_C, the corresponding per-observation analog to pass in
    is `SE^2 * (n_T + n_C)`.

    Args:
        s2: Per-observation variance (must be positive).
        n: Combined sample size across treatment + control (must be >= 1).
        sequential_tuning_parameter: Tuning parameter `N`.
        alpha: Significance level.
        rho: Optional precomputed rho. If omitted, derived from alpha and N.

    Returns:
        Half-width of the confidence sequence.
    """
    if s2 <= 0:
        raise StatisticError("s2 must be positive")
    if n < 1:
        raise StatisticError("Sample size must be at least 1")

    if rho is None:
        rho = sequential_rho(alpha, sequential_tuning_parameter)

    n_rho_sq_p1 = n * rho**2 + 1
    return float(np.sqrt(s2) * np.sqrt(2 * n_rho_sq_p1 * np.log(np.sqrt(n_rho_sq_p1) / alpha) / (n * rho) ** 2))


def sequential_p_value(
    point_estimate: float,
    pooled_variance: float,
    n: int,
    sequential_tuning_parameter: float,
    rho: float | None = None,
    alpha: float | None = None,
    null_hypothesis_value: float = 0.0,
) -> float:
    """
    Two-sided always-valid p-value, derived analytically from the e-value.

    Implements eq. 155 of Waudby-Smith et al. 2023:
        t^2     = (theta_hat - theta_0)^2 * n / SE^2
        evalue  = exp( rho^2 * t^2 / (2*(n*rho^2 + 1)) ) / sqrt(n*rho^2 + 1)
        p_value = min(1 / evalue, 1)

    Here `pooled_variance` is SE^2 of the estimator (e.g. Var_T/n_T + Var_C/n_C for the
    two-sample diff). The `* n` factor is applied internally.

    The e-value is < 1 (and so the p-value clamps to 1) until enough evidence has
    accumulated. Early-in-experiment p-values of exactly 1.0 are expected behavior,
    not a bug.

    Args:
        point_estimate: Estimated difference between treatment and control.
        pooled_variance: Variance of the estimator (i.e. SE^2).
        n: Combined sample size.
        sequential_tuning_parameter: Tuning parameter `N`.
        rho: Optional precomputed rho. If omitted, must supply alpha.
        alpha: Significance level used to derive rho when not given.
        null_hypothesis_value: Value under the null hypothesis.

    Returns:
        Always-valid p-value in (0, 1].
    """
    if pooled_variance <= 0:
        raise StatisticError("Pooled variance must be positive")
    if n < 1:
        raise StatisticError("Sample size must be at least 1")

    if rho is None:
        if alpha is None:
            raise StatisticError("Must supply either rho or alpha to compute sequential p-value")
        rho = sequential_rho(alpha, sequential_tuning_parameter)

    t_squared = (point_estimate - null_hypothesis_value) ** 2 * n / pooled_variance
    n_rho_sq_p1 = n * rho**2 + 1
    # Work in log-space to avoid np.exp overflowing to +inf for extremely strong evidence;
    # the e-value can be astronomical but 1/e-value just collapses smoothly toward 0.
    log_evalue = rho**2 * t_squared / (2 * n_rho_sq_p1) - 0.5 * np.log(n_rho_sq_p1)
    if log_evalue <= 0:
        return 1.0
    return float(min(np.exp(-log_evalue), 1.0))


def check_normal_approximation_validity(statistic: AnyStatistic) -> bool:
    """
    Check if normal approximation is valid for the given statistic.

    For proportions: requires np > 5 and n(1-p) > 5
    For other statistics: requires n >= 30 (rule of thumb)

    Args:
        statistic: Statistic to check

    Returns:
        True if normal approximation is likely valid
    """
    n = get_sample_size(statistic)

    if isinstance(statistic, ProportionStatistic):
        p = statistic.proportion
        return n * p >= 5 and n * (1 - p) >= 5
    else:
        return n >= 30
