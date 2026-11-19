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
                "the_fewest_treatment_trials_the_test_takes",
                Proportion(trials=5, successes=2),
                Proportion(trials=200, successes=10),
                0.05,
                False,
                0.35,
            ),
        ]
    )
    def test_compares_the_treatment_with_the_control(
        self, _name: str, treatment: Proportion, control: Proportion, alpha: float, significant: bool, difference: float
    ) -> None:
        result = sequential_proportion_test(treatment, control, alpha=alpha)

        assert result is not None
        assert (result.is_significant, round(result.difference, 3)) == (significant, difference)
        lower, upper = result.confidence_interval
        assert (result.p_value < alpha) == significant
        assert lower <= result.difference <= upper
        assert (lower > 0 or upper < 0) == significant

    @parameterized.expand(
        [
            ("no_control_trials", Proportion(trials=200, successes=10), Proportion(trials=0, successes=0)),
            ("too_few_treatment_trials", Proportion(trials=4, successes=1), Proportion(trials=200, successes=10)),
            (
                "no_successes_in_either_group",
                Proportion(trials=1000, successes=0),
                Proportion(trials=1000, successes=0),
            ),
            (
                "every_treated_and_no_control_success",
                Proportion(trials=10, successes=10),
                Proportion(trials=200, successes=0),
            ),
        ]
    )
    def test_returns_none_when_the_test_cannot_run(
        self, _name: str, treatment: Proportion, control: Proportion
    ) -> None:
        assert sequential_proportion_test(treatment, control) is None

    @parameterized.expand(
        [
            ("alpha_above_one", Proportion(trials=1000, successes=20), Proportion(trials=1000, successes=0), 5.0),
            ("successes_without_trials", Proportion(trials=0, successes=5), Proportion(trials=200, successes=0), 0.05),
            (
                "negative_control_successes",
                Proportion(trials=200, successes=0),
                Proportion(trials=200, successes=-1),
                0.05,
            ),
        ]
    )
    def test_raises_on_invalid_input(
        self, _name: str, treatment: Proportion, control: Proportion, alpha: float
    ) -> None:
        with self.assertRaises(ValueError):
            sequential_proportion_test(treatment, control, alpha=alpha)
