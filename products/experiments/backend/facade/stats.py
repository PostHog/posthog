"""Statistical tests of the experiments stats code, for callers outside the experiments product."""

from products.experiments.backend.facade.contracts import Proportion, ProportionTestResult
from products.experiments.stats.frequentist.method import FrequentistConfig, FrequentistMethod
from products.experiments.stats.shared.enums import DifferenceType
from products.experiments.stats.shared.statistics import ProportionStatistic, StatisticError


def sequential_proportion_test(
    treatment: Proportion, control: Proportion, *, alpha: float = 0.05
) -> ProportionTestResult | None:
    """Compares two proportions with the sequential test of experiments. A caller can run it again on every new count,
    because the test keeps its false positive rate at `alpha` however often it looks. Returns None when the test can't
    run: a group has too few trials, or each group has only one outcome, so there is no variance. Raises ValueError when
    a proportion has more successes than trials."""
    treatment_stat = ProportionStatistic(n=treatment.trials, sum=treatment.successes)
    control_stat = ProportionStatistic(n=control.trials, sum=control.successes)
    config = FrequentistConfig(alpha=alpha, difference_type=DifferenceType.ABSOLUTE, sequential_testing_enabled=True)
    try:
        result = FrequentistMethod(config).run_test(treatment_stat, control_stat)
    except StatisticError:
        return None
    return ProportionTestResult(
        difference=result.point_estimate,
        confidence_interval=result.confidence_interval,
        p_value=result.p_value,
        is_significant=result.is_significant,
    )
