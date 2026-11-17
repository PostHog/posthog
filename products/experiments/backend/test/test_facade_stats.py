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
            ("no_successes_in_either_group", 0, 0, False, 0.0),
        ]
    )
    def test_compares_the_treatment_with_the_control(
        self, _name: str, treatment_successes: int, control_successes: int, significant: bool, difference: float
    ) -> None:
        result = sequential_proportion_test(
            Proportion(trials=1000, successes=treatment_successes), Proportion(trials=1000, successes=control_successes)
        )

        assert (result.is_significant, round(result.difference, 3)) == (significant, difference)
