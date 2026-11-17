"""Statistical tests of the experiments stats code, for callers outside the experiments product."""

from products.experiments.backend.facade.contracts import Proportion, ProportionTestResult
from products.experiments.stats.frequentist.method import FrequentistConfig, FrequentistMethod
from products.experiments.stats.shared.enums import DifferenceType
from products.experiments.stats.shared.statistics import ProportionStatistic


def sequential_proportion_test(
    treatment: Proportion, control: Proportion, *, alpha: float = 0.05
) -> ProportionTestResult:
    """Compares two proportions with the sequential test of experiments. A caller can run it again on every new count,
    because the test keeps its false positive rate at `alpha` however often it looks. Raises ValueError when a
    proportion has no trials or more successes than trials."""
    treatment_stat = ProportionStatistic(n=treatment.trials, sum=treatment.successes)
    control_stat = ProportionStatistic(n=control.trials, sum=control.successes)
    # When every trial of both groups has the same outcome, the pooled variance is zero and the test can't run. The two
    # proportions are equal, so there is no difference to find.
    pooled = (treatment.successes + control.successes) / (treatment.trials + control.trials)
    if pooled in (0.0, 1.0):
        return ProportionTestResult(difference=0.0, confidence_interval=(0.0, 0.0), p_value=1.0, is_significant=False)
    config = FrequentistConfig(alpha=alpha, difference_type=DifferenceType.ABSOLUTE, sequential_testing_enabled=True)
    result = FrequentistMethod(config).run_test(treatment_stat, control_stat)
    return ProportionTestResult(
        difference=result.point_estimate,
        confidence_interval=result.confidence_interval,
        p_value=result.p_value,
        is_significant=result.is_significant,
    )
