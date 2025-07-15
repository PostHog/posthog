from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..shared.statistics import AnyStatistic, StatisticError
from ..shared.enums import DifferenceType
from .utils import (
    calculate_point_estimate,
    calculate_variance_pooled,
    calculate_welch_satterthwaite_df,
    calculate_t_statistic,
    calculate_p_value,
    calculate_confidence_interval,
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

        point_estimate = calculate_point_estimate(treatment_stat, control_stat, difference_type)

        # Calculate variance and degrees of freedom
        pooled_variance = calculate_variance_pooled(treatment_stat, control_stat, difference_type)
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
