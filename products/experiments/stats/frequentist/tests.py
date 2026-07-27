import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..shared.enums import DifferenceType
from ..shared.statistics import AnyStatistic, StatisticError
from ..shared.utils import get_sample_size
from .utils import (
    calculate_confidence_interval,
    calculate_p_value,
    calculate_point_estimate,
    calculate_t_statistic,
    calculate_variance_pooled,
    calculate_welch_satterthwaite_df,
    sequential_interval_halfwidth,
    sequential_p_value,
    sequential_rho,
    validate_sample_sizes,
)


@dataclass
class TestResult:
    """Result of a statistical test."""

    point_estimate: float
    """Point estimate of the difference between treatment and control groups."""

    confidence_interval: tuple[float, float]
    """Confidence interval of the difference between treatment and control groups."""

    p_value: float

    test_statistic: float
    """Test statistic of the test (t-statistic, etc.)."""

    degrees_of_freedom: float

    is_significant: bool
    """Whether the test is significant at the alpha level."""

    test_type: str
    """Type of test (two_sided, greater, less, etc.)."""

    alpha: float
    """Significance level."""


class StatisticalTest(ABC):
    """Abstract base class for all statistical tests."""

    def __init__(self, alpha: float = 0.05):
        """
        Initialize test with significance level.

        Args:
            alpha: Significance level (default: 0.05)
        """
        if not (0 < alpha < 1):
            raise StatisticError("Alpha must be between 0 and 1")
        self.alpha = alpha

    @property
    @abstractmethod
    def test_type(self) -> str:
        """Return the test type identifier."""
        pass

    @property
    @abstractmethod
    def p_value_type(self) -> str:
        """Return the p-value calculation type (two_sided, greater, less)."""
        pass

    @abstractmethod
    def run_test(
        self,
        treatment_stat: AnyStatistic,
        control_stat: AnyStatistic,
        difference_type: DifferenceType = DifferenceType.RELATIVE,
        **kwargs,
    ) -> TestResult:
        """
        Run the statistical test.

        Args:
            treatment_stat: Treatment group statistic
            control_stat: Control group statistic
            difference_type: Type of difference to calculate
            **kwargs: Additional test-specific parameters

        Returns:
            TestResult object
        """
        pass


class TwoSidedTTest(StatisticalTest):
    """Standard two-sided t-test using Welch's method for unequal variances."""

    @property
    def test_type(self) -> str:
        return "two_sided"

    @property
    def p_value_type(self) -> str:
        return "two_sided"

    def run_test(
        self,
        treatment_stat: AnyStatistic,
        control_stat: AnyStatistic,
        difference_type: DifferenceType = DifferenceType.RELATIVE,
        **kwargs,
    ) -> TestResult:
        """Run two-sided t-test."""
        validate_sample_sizes(treatment_stat, control_stat)

        unadjusted_mean = kwargs.get("unadjusted_mean")
        point_estimate = calculate_point_estimate(treatment_stat, control_stat, difference_type, unadjusted_mean)

        # Calculate variance and degrees of freedom
        pooled_variance = calculate_variance_pooled(treatment_stat, control_stat, difference_type, unadjusted_mean)
        degrees_of_freedom = calculate_welch_satterthwaite_df(treatment_stat, control_stat)

        # Calculate test statistic and p-value
        t_statistic = calculate_t_statistic(point_estimate, pooled_variance)
        p_value = calculate_p_value(t_statistic, degrees_of_freedom, self.p_value_type)

        # Calculate confidence interval
        confidence_interval = calculate_confidence_interval(
            point_estimate, pooled_variance, degrees_of_freedom, self.alpha, self.test_type
        )

        return TestResult(
            point_estimate=point_estimate,
            confidence_interval=confidence_interval,
            p_value=p_value,
            test_statistic=t_statistic,
            degrees_of_freedom=degrees_of_freedom,
            is_significant=p_value < self.alpha,
            test_type=self.test_type,
            alpha=self.alpha,
        )


class SequentialTwoSidedTTest(StatisticalTest):
    """
    Two-sided sequential test producing always-valid p-values and confidence
    sequences, following Waudby-Smith et al. 2023
    (https://arxiv.org/pdf/2103.06476v7.pdf).

    Unlike a fixed-horizon t-test, the result is robust to continuous monitoring
    ("peeking"): the false positive rate stays bounded by alpha no matter how many
    times the experimenter checks the dashboard. The cost is a wider confidence
    interval that is narrowest near n ~ tuning_parameter.
    """

    DEFAULT_TUNING_PARAMETER: float = 5000.0

    def __init__(self, alpha: float = 0.05, sequential_tuning_parameter: float = DEFAULT_TUNING_PARAMETER):
        super().__init__(alpha=alpha)
        if sequential_tuning_parameter <= 0:
            raise StatisticError("Sequential tuning parameter must be positive")
        self.sequential_tuning_parameter = sequential_tuning_parameter
        self._rho = sequential_rho(alpha, sequential_tuning_parameter)

    @property
    def test_type(self) -> str:
        return "sequential_two_sided"

    @property
    def p_value_type(self) -> str:
        return "two_sided"

    def run_test(
        self,
        treatment_stat: AnyStatistic,
        control_stat: AnyStatistic,
        difference_type: DifferenceType = DifferenceType.RELATIVE,
        **kwargs,
    ) -> TestResult:
        validate_sample_sizes(treatment_stat, control_stat)

        unadjusted_mean = kwargs.get("unadjusted_mean")
        point_estimate = calculate_point_estimate(treatment_stat, control_stat, difference_type, unadjusted_mean)
        pooled_variance = calculate_variance_pooled(treatment_stat, control_stat, difference_type, unadjusted_mean)
        n = get_sample_size(treatment_stat) + get_sample_size(control_stat)

        # No t-distribution in the always-valid construction, so neither the degrees of
        # freedom nor a t-statistic carry meaning here. Surface both as NaN so downstream
        # consumers don't quietly use a meaningless value.
        degrees_of_freedom = math.nan
        t_statistic = math.nan

        p_value = sequential_p_value(
            point_estimate=point_estimate,
            pooled_variance=pooled_variance,
            n=n,
            sequential_tuning_parameter=self.sequential_tuning_parameter,
            rho=self._rho,
        )
        # The Waudby-Smith eq. 9 takes the per-observation variance, but the rest of
        # PostHog's frequentist plumbing passes around the variance of the estimator
        # (SE^2 = Var_T/n_T + Var_C/n_C). Convert by multiplying by the combined sample
        # size; this keeps the e-value (eq. 155) and the half-width (eq. 9) consistent.
        s2_per_observation = pooled_variance * n
        halfwidth = sequential_interval_halfwidth(
            s2=s2_per_observation,
            n=n,
            sequential_tuning_parameter=self.sequential_tuning_parameter,
            alpha=self.alpha,
            rho=self._rho,
        )
        confidence_interval = (point_estimate - halfwidth, point_estimate + halfwidth)

        return TestResult(
            point_estimate=point_estimate,
            confidence_interval=confidence_interval,
            p_value=p_value,
            test_statistic=t_statistic,
            degrees_of_freedom=degrees_of_freedom,
            is_significant=p_value < self.alpha,
            test_type=self.test_type,
            alpha=self.alpha,
        )
