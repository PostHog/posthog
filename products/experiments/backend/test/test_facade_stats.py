from django.test import SimpleTestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import Proportion
from products.experiments.backend.facade.stats import sequential_proportion_test


class TestSequentialProportionTest(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a_clear_rise",
                Proportion(trials=1000, successes=200),
                Proportion(trials=1000, successes=100),
                0.05,
                True,
                0.1,
            ),
            # A single fixed-horizon test calls this significant, which repeated looks would turn into false alarms.
            (
                "a_rise_that_one_look_would_call_significant",
                Proportion(trials=1000, successes=60),
                Proportion(trials=1000, successes=40),
                0.05,
                False,
                0.02,
            ),
            (
                "a_rise_over_a_zero_control_rate",
                Proportion(trials=1000, successes=20),
                Proportion(trials=1000, successes=0),
                0.05,
                True,
                0.02,
            ),
            (
                "a_rise_that_a_stricter_alpha_rejects",
                Proportion(trials=1000, successes=12),
                Proportion(trials=1000, successes=0),
                0.01,
                False,
                0.012,
            ),
            (
                "every_treated_and_no_control_success",
                Proportion(trials=10, successes=10),
                Proportion(trials=200, successes=0),
                0.05,
                True,
                0.912,
            ),
        ]
    )
    def test_compares_the_treatment_with_the_control(
        self, _name: str, treatment: Proportion, control: Proportion, alpha: float, significant: bool, difference: float
    ) -> None:
        result = sequential_proportion_test(treatment, control, alpha=alpha)

        assert result is not None
        assert (result.is_significant, round(result.difference, 3)) == (significant, difference)

    @parameterized.expand(
        [
            (
                "no_successes_in_either_group",
                Proportion(trials=1000, successes=0),
                Proportion(trials=1000, successes=0),
            ),
            ("no_trials", Proportion(trials=0, successes=0), Proportion(trials=200, successes=10)),
            (
                "too_few_trials_with_one_outcome_each",
                Proportion(trials=3, successes=3),
                Proportion(trials=200, successes=0),
            ),
        ]
    )
    def test_returns_none_when_the_test_cannot_run(
        self, _name: str, treatment: Proportion, control: Proportion
    ) -> None:
        assert sequential_proportion_test(treatment, control) is None
