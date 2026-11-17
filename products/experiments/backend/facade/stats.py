"""Statistical tests of the experiments stats code, for callers outside the experiments product."""

from products.experiments.backend.facade.contracts import Proportion, ProportionTestResult
from products.experiments.stats.frequentist.tests import SequentialTwoSidedTTest
from products.experiments.stats.frequentist.utils import validate_sample_sizes
from products.experiments.stats.shared.enums import DifferenceType
from products.experiments.stats.shared.statistics import ProportionStatistic, StatisticError


def sequential_proportion_test(
    treatment: Proportion, control: Proportion, *, alpha: float = 0.05
) -> ProportionTestResult | None:
    """Compares two proportions with the sequential test that experiments use. A caller can run it again on every new
    count, because the test keeps its false positive rate at or below `alpha` however often it looks.

    The test runs on the counts with one success and one failure added to each group (Agresti-Caffo), so a group at
    0% or 100% still has a variance. `difference` and `confidence_interval` come from those counts, which pull each
    rate toward 50%, a small group more than a large one: 10/10 against 0/200 gives 0.912, not 1, and 50/1000 against
    0/5 gives -0.092, not 0.05. Read the sign of `difference` only when `is_significant` is true. The interval can
    reach past [-1, 1] at small counts, and `p_value` depends on `alpha`, so compare it only with that `alpha`.

    Returns None when a group has fewer than 5 trials. Raises ValueError when trials or successes are negative,
    successes exceed trials, or `alpha` is not between 0 and 1."""
    test = SequentialTwoSidedTTest(alpha=alpha)
    for proportion in (treatment, control):
        if not 0 <= proportion.successes <= proportion.trials:
            raise ValueError(f"A proportion needs 0 <= successes <= trials, got {proportion}")
    try:
        # On the real counts, because the pseudo counts add two trials to each group.
        validate_sample_sizes(
            ProportionStatistic(n=treatment.trials, sum=treatment.successes),
            ProportionStatistic(n=control.trials, sum=control.successes),
        )
    except StatisticError:
        return None
    result = test.run_test(_with_pseudo_counts(treatment), _with_pseudo_counts(control), DifferenceType.ABSOLUTE)
    return ProportionTestResult(
        difference=result.point_estimate,
        confidence_interval=result.confidence_interval,
        p_value=result.p_value,
        is_significant=result.is_significant,
    )


def _with_pseudo_counts(proportion: Proportion) -> ProportionStatistic:
    return ProportionStatistic(n=proportion.trials + 2, sum=proportion.successes + 1)
