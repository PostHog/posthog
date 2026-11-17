from django.test import SimpleTestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import Proportion
from products.experiments.backend.facade.stats import sequential_proportion_test


class TestSequentialProportionTest(SimpleTestCase):
    @parameterized.expand(
        [
            ("a_clear_rise", 200, 100, True, 0.1),
            # A single fixed-horizon test calls this significant, which repeated looks would turn into false alarms.
            ("a_rise_that_one_look_would_call_significant", 60, 40, False, 0.02),
        ]
    )
    def test_compares_the_treatment_with_the_control(
        self, _name: str, treatment_successes: int, control_successes: int, significant: bool, difference: float
    ) -> None:
        result = sequential_proportion_test(
            Proportion(trials=1000, successes=treatment_successes), Proportion(trials=1000, successes=control_successes)
        )

        assert result is not None
        assert (result.is_significant, round(result.difference, 3)) == (significant, difference)

    @parameterized.expand(
        [
            (
                "no_successes_in_either_group",
                Proportion(trials=1000, successes=0),
                Proportion(trials=1000, successes=0),
            ),
            ("one_outcome_in_each_group", Proportion(trials=10, successes=10), Proportion(trials=200, successes=0)),
            ("too_few_trials", Proportion(trials=1, successes=1), Proportion(trials=200, successes=10)),
        ]
    )
    def test_returns_none_when_the_test_cannot_run(
        self, _name: str, treatment: Proportion, control: Proportion
    ) -> None:
        assert sequential_proportion_test(treatment, control) is None
