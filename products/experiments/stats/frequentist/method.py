from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..shared.enums import DifferenceType
from ..shared.statistics import AnyStatistic, StatisticError
from .tests import SequentialTwoSidedTTest, StatisticalTest, TestResult, TwoSidedTTest


class TestType(Enum):
    """Available test types."""

    TWO_SIDED = "two_sided"


DEFAULT_SEQUENTIAL_TUNING_PARAMETER: float = SequentialTwoSidedTTest.DEFAULT_TUNING_PARAMETER


@dataclass
class FrequentistConfig:
    """Configuration for frequentist testing."""

    alpha: float = 0.05
    difference_type: DifferenceType = DifferenceType.RELATIVE
    test_type: TestType = TestType.TWO_SIDED
    sequential_testing_enabled: bool = False
    sequential_tuning_parameter: float = DEFAULT_SEQUENTIAL_TUNING_PARAMETER

    def __post_init__(self):
        """Validate configuration parameters."""
        if not (0 < self.alpha < 1):
            raise StatisticError("Alpha must be between 0 and 1")
        if self.sequential_testing_enabled and self.sequential_tuning_parameter <= 0:
            raise StatisticError("Sequential tuning parameter must be positive")


class FrequentistMethod:
    """
    Main class for frequentist A/B testing.

    This class provides a high-level interface for running statistical tests
    on A/B experiment data using various test types and configurations.

    Example:
        # Basic usage
        method = FrequentistMethod()
        result = method.run_test(treatment_stat, control_stat)

        # With custom configuration
        config = FrequentistConfig(
            alpha=0.01,
            difference_type=DifferenceType.ABSOLUTE,
            test_type=TestType.TWO_SIDED
        )
        method = FrequentistMethod(config)
        result = method.run_test(treatment_stat, control_stat)
    """

    def __init__(self, config: Optional[FrequentistConfig] = None):
        """
        Initialize FrequentistMethod with configuration.

        Args:
            config: Configuration object (uses defaults if None)
        """
        self.config = config or FrequentistConfig()

    def run_test(self, treatment_stat: AnyStatistic, control_stat: AnyStatistic, **kwargs) -> TestResult:
        """
        Run statistical test comparing treatment vs control.

        Args:
            treatment_stat: Treatment group statistic
            control_stat: Control group statistic
            **kwargs: Additional parameters (overrides config values)

        Returns:
            TestResult with all statistical outputs

        Raises:
            StatisticError: If inputs are invalid or test fails
        """
        if self.config.test_type == TestType.TWO_SIDED:
            if self.config.sequential_testing_enabled:
                test: StatisticalTest = SequentialTwoSidedTTest(
                    alpha=self.config.alpha,
                    sequential_tuning_parameter=self.config.sequential_tuning_parameter,
                )
            else:
                test = TwoSidedTTest(self.config.alpha)
        else:
            raise StatisticError(f"Unknown test type: {self.config.test_type}")

        try:
            return test.run_test(
                treatment_stat=treatment_stat,
                control_stat=control_stat,
                difference_type=self.config.difference_type,
                **kwargs,
            )
        except Exception as e:
            raise StatisticError(f"Test execution failed: {str(e)}") from e
