import numpy as np
from scipy import stats

from products.experiments.stats.shared.enums import DifferenceType
from products.experiments.stats.shared.utils import get_mean, get_sample_size, get_variance

from ..shared.statistics import AnyStatistic, ProportionStatistic, StatisticError


def calculate_point_estimate(
    treatment_stat: AnyStatistic,
    control_stat: AnyStatistic,
    difference_type: DifferenceType,
) -> float:
    """
    Calculate point estimate for treatment vs control comparison.

    Args:
        treatment_stat: Treatment group statistic
        control_stat: Control group statistic
        difference_type: Type of difference to calculate

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
        if abs(control_mean) < 1e-10:
            raise StatisticError("Control mean cannot be zero for relative difference calculation")
        return (treatment_mean - control_mean) / control_mean

    else:
        raise StatisticError(f"Unknown difference type: {difference_type}")


def calculate_variance_pooled(
    treatment_stat: AnyStatistic, control_stat: AnyStatistic, difference_type: DifferenceType
) -> float:
    """
    Calculate pooled variance for treatment vs control comparison.

    For absolute differences: Var = Var_T/n_T + Var_C/n_C
    For relative differences: Uses delta method approximation

    Args:
        treatment_stat: Treatment group statistic
        control_stat: Control group statistic
        difference_type: Type of difference calculation

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

        if abs(control_mean) < 1e-10:
            raise StatisticError("Control mean cannot be zero for relative variance calculation")

        # Var(Y/X) ≈ Var(Y)/X² + Y²Var(X)/X⁴ - 2Y*Cov(X,Y)/X³
        # Since treatment and control are independent, Cov(X,Y) = 0
        var_y_over_x_squared = treatment_var / (treatment_n * control_mean**2)
        y_squared_var_x_over_x_fourth = (treatment_mean**2 * control_var) / (control_n * control_mean**4)

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
