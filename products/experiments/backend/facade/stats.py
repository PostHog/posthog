"""Statistical tests of the experiments stats code, for callers outside the experiments product."""

from products.experiments.backend.facade.contracts import Proportion, ProportionTestResult
from products.experiments.stats.frequentist.tests import SequentialTwoSidedTTest
from products.experiments.stats.frequentist.utils import validate_sample_sizes
from products.experiments.stats.shared.enums import DifferenceType
from products.experiments.stats.shared.statistics import ProportionStatistic, StatisticError


def sequential_proportion_test(
    treatment: Proportion, control: Proportion, *, alpha: float = 0.05
) -> ProportionTestResult | None:
    """Compares two proportions with the sequential test of experiments. A caller can run it again on every new count,
    because the test keeps its false positive rate at `alpha` however often it looks.

    Returns None when the test can't run: a group has fewer than 5 trials, or both groups are at 0%, or both at 100%,
    so there is no variance. When one group is at 0% and the other at 100%, the test runs on the counts with one
    success and one failure added to each group, so the result is not exactly 100% against 0%.

    Raises ValueError when trials or successes are negative, successes exceed trials, or `alpha` is not between 0
    and 1."""
    test = SequentialTwoSidedTTest(alpha=alpha)
    if treatment.trials == 0 or control.trials == 0:
        return None
    treatment_stat = ProportionStatistic(n=treatment.trials, sum=treatment.successes)
    control_stat = ProportionStatistic(n=control.trials, sum=control.successes)
    try:
        # Checked on the real counts, because the pseudo counts below add two trials to each group.
        validate_sample_sizes(treatment_stat, control_stat)
        if _completely_separated(treatment, control):
            # Each group alone has zero variance, so the pooled variance is zero although the groups differ as much
            # as they can. One pseudo success and one pseudo failure per group (Agresti-Caffo) give the test a variance.
            treatment_stat = ProportionStatistic(n=treatment.trials + 2, sum=treatment.successes + 1)
            control_stat = ProportionStatistic(n=control.trials + 2, sum=control.successes + 1)
        result = test.run_test(treatment_stat, control_stat, DifferenceType.ABSOLUTE)
    except StatisticError:
        return None
    return ProportionTestResult(
        difference=result.point_estimate,
        confidence_interval=result.confidence_interval,
        p_value=result.p_value,
        is_significant=result.is_significant,
    )


def _completely_separated(treatment: Proportion, control: Proportion) -> bool:
    return {treatment.successes / treatment.trials, control.successes / control.trials} == {0.0, 1.0}
