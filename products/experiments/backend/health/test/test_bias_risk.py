from unittest import TestCase

from parameterized import parameterized

from posthog.schema import BiasRisk, MultipleVariantHandling

from products.experiments.backend.health.checks.bias_risk import MULTIPLE_VARIANT_BIAS_THRESHOLD, evaluate_bias_risk
from products.feature_flags.backend.facade.edits import FlagVariant


def _split(*percentages: float) -> tuple[FlagVariant, ...]:
    keys = ("control", "test", "third")
    return tuple(FlagVariant(key=key, rollout_percentage=pct) for key, pct in zip(keys, percentages))


UNEVEN_2WAY = _split(80, 20)
EVEN_2WAY = _split(50, 50)
# Auto-distribution for 3 variants — should be treated as even, not uneven.
AUTO_EVEN_3WAY = _split(34, 33, 33)


class TestEvaluateBiasRisk(TestCase):
    def test_observed_bias_returns_populated_risk(self):
        # 20 / (800 + 200 + 20) ≈ 1.96%, well above the 0.1% threshold.
        result = evaluate_bias_risk(
            UNEVEN_2WAY, frozenset(), MultipleVariantHandling.EXCLUDE, {"control": 800, "test": 200, "$multiple": 20}
        )
        self.assertIsInstance(result, BiasRisk)
        assert result is not None
        self.assertAlmostEqual(result.multiple_variant_percentage, 20 / 1020 * 100, places=5)

    def test_auto_even_3way_is_treated_as_even(self):
        # 34/33/33 is what the auto-distribution produces — must NOT be flagged as uneven.
        result = evaluate_bias_risk(
            AUTO_EVEN_3WAY,
            frozenset(),
            MultipleVariantHandling.EXCLUDE,
            {"a": 340, "b": 330, "c": 330, "$multiple": 50},
        )
        self.assertIsNone(result)

    @parameterized.expand(
        [
            (
                "first_seen_handling",
                UNEVEN_2WAY,
                MultipleVariantHandling.FIRST_SEEN,
                {"control": 800, "test": 200, "$multiple": 50},
            ),
            (
                "even_2way_split",
                EVEN_2WAY,
                MultipleVariantHandling.EXCLUDE,
                {"control": 500, "test": 500, "$multiple": 50},
            ),
            (
                "zero_multiple_share",
                UNEVEN_2WAY,
                MultipleVariantHandling.EXCLUDE,
                {"control": 800, "test": 200, "$multiple": 0},
            ),
            (
                "empty_total_exposures",
                UNEVEN_2WAY,
                MultipleVariantHandling.EXCLUDE,
                {},
            ),
            (
                "all_zero_exposures",
                UNEVEN_2WAY,
                MultipleVariantHandling.EXCLUDE,
                {"control": 0, "test": 0, "$multiple": 0},
            ),
            (
                "empty_variants",
                (),
                MultipleVariantHandling.EXCLUDE,
                {"control": 800, "test": 200, "$multiple": 50},
            ),
            (
                "variant_at_zero_beside_an_even_split",
                _split(50, 50, 0),
                MultipleVariantHandling.EXCLUDE,
                {"control": 500, "test": 500, "$multiple": 50},
            ),
            (
                "one_variant_at_100",
                _split(0, 100),
                MultipleVariantHandling.EXCLUDE,
                {"control": 500, "test": 500, "$multiple": 50},
            ),
            (
                "fewer_users_in_several_variants_than_the_floor",
                UNEVEN_2WAY,
                MultipleVariantHandling.EXCLUDE,
                {"control": 80, "test": 20, "$multiple": 4},
            ),
        ]
    )
    def test_returns_none_when_not_at_risk(self, _name, variants, handling, exposures):
        result = evaluate_bias_risk(variants, frozenset(), handling, exposures)
        self.assertIsNone(result)

    def test_excluded_variant_leaves_an_even_split_of_the_compared_variants(self):
        result = evaluate_bias_risk(
            _split(50, 25, 25),
            frozenset({"control"}),
            MultipleVariantHandling.EXCLUDE,
            {"test": 500, "third": 500, "$multiple": 50},
        )
        self.assertIsNone(result)

    def test_threshold_boundary_strictly_greater_than(self):
        # Exactly at threshold (10 / 10000 = 0.1%) should NOT trigger — uses strict `>`.
        result = evaluate_bias_risk(
            UNEVEN_2WAY, frozenset(), MultipleVariantHandling.EXCLUDE, {"control": 7990, "test": 2000, "$multiple": 10}
        )
        self.assertIsNone(result)

    def test_threshold_boundary_just_above(self):
        # 11 / 10000 = 0.11% — above the 0.1% threshold.
        result = evaluate_bias_risk(
            UNEVEN_2WAY, frozenset(), MultipleVariantHandling.EXCLUDE, {"control": 7989, "test": 2000, "$multiple": 11}
        )
        assert result is not None
        self.assertGreater(result.multiple_variant_percentage, MULTIPLE_VARIANT_BIAS_THRESHOLD)
