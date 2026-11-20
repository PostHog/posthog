"""Statistical tests of the experiments stats code, for callers outside the experiments product."""

from products.experiments.backend.facade.contracts import Proportion, ProportionTestResult
from products.experiments.stats.frequentist.tests import SequentialTwoSidedTTest
from products.experiments.stats.shared.enums import DifferenceType
from products.experiments.stats.shared.statistics import ProportionStatistic, StatisticError


def sequential_proportion_test(
    treatment: Proportion, control: Proportion, *, alpha: float = 0.05
) -> ProportionTestResult | None:
    """Compares two proportions with the sequential test that experiments use. A caller can run it again on every new
    count, because the test keeps its false positive rate at or below `alpha` however often it looks.

    `difference` is treatment minus control in proportion units. The interval can reach past [-1, 1] at small counts,
    and `p_value` depends on `alpha`, so compare it only with that `alpha`.

    The test takes the variance of each group from its own rate, so a group at 0% or 100% adds no variance and makes
    the test overconfident: 5 of 5 against 1 of 20 is significant. A caller with small groups should add its own
    pseudo counts, such as one success and one failure per group.

    Returns None when a group has fewer than 5 trials, or when every group is at 0% or 100%, because the test needs a
    variance above zero. Raises ValueError when trials or successes are negative, successes exceed trials, or `alpha`
    is not between 0 and 1."""
    test = SequentialTwoSidedTTest(alpha=alpha)
    for proportion in (treatment, control):
        if not 0 <= proportion.successes <= proportion.trials:
            raise ValueError(f"A proportion needs 0 <= successes <= trials, got {proportion}")
    try:
        result = test.run_test(_statistic(treatment), _statistic(control), DifferenceType.ABSOLUTE)
    except StatisticError:
        return None
    return ProportionTestResult(
        difference=result.point_estimate,
        confidence_interval=result.confidence_interval,
        p_value=result.p_value,
        is_significant=result.is_significant,
    )


def _statistic(proportion: Proportion) -> ProportionStatistic:
    return ProportionStatistic(n=proportion.trials, sum=proportion.successes)
