from unittest import TestCase

from parameterized import parameterized

from posthog.schema import BiasRisk, ExperimentStatsBaseValidated, MultipleVariantHandling

from products.experiments.backend.analysis_health import (
    MULTIPLE_VARIANT_BIAS_THRESHOLD,
    evaluate_bias_risk,
    evaluate_funnel_power_risk,
)

UNEVEN_2WAY = [{"rollout_percentage": 80}, {"rollout_percentage": 20}]
EVEN_2WAY = [{"rollout_percentage": 50}, {"rollout_percentage": 50}]
# Auto-distribution for 3 variants — should be treated as even, not uneven.
AUTO_EVEN_3WAY = [{"rollout_percentage": 34}, {"rollout_percentage": 33}, {"rollout_percentage": 33}]


class TestEvaluateBiasRisk(TestCase):
    def test_observed_bias_returns_populated_risk(self):
        # 20 / (800 + 200 + 20) ≈ 1.96%, well above the 0.1% threshold.
        result = evaluate_bias_risk(
            UNEVEN_2WAY, MultipleVariantHandling.EXCLUDE, {"control": 800, "test": 200, "$multiple": 20}
        )
        self.assertIsInstance(result, BiasRisk)
        assert result is not None
        self.assertAlmostEqual(result.multiple_variant_percentage, 20 / 1020 * 100, places=5)

    def test_auto_even_3way_is_treated_as_even(self):
        # 34/33/33 is what the auto-distribution produces — must NOT be flagged as uneven.
        result = evaluate_bias_risk(
            AUTO_EVEN_3WAY, MultipleVariantHandling.EXCLUDE, {"a": 340, "b": 330, "c": 330, "$multiple": 50}
        )
        self.assertIsNone(result)

    def test_reordered_auto_even_is_uneven(self):
        # 33/34/33 doesn't match the auto-distribution result (34/33/33) — counts as uneven,
        # mirroring the frontend's positional `isEvenlyDistributed` check.
        reordered = [{"rollout_percentage": 33}, {"rollout_percentage": 34}, {"rollout_percentage": 33}]
        result = evaluate_bias_risk(
            reordered, MultipleVariantHandling.EXCLUDE, {"a": 330, "b": 340, "c": 330, "$multiple": 50}
        )
        self.assertIsNotNone(result)

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
                [],
                MultipleVariantHandling.EXCLUDE,
                {"control": 800, "test": 200, "$multiple": 50},
            ),
            (
                "none_variants",
                None,
                MultipleVariantHandling.EXCLUDE,
                {"control": 800, "test": 200, "$multiple": 50},
            ),
        ]
    )
    def test_returns_none_when_not_at_risk(self, _name, flag_variants, handling, exposures):
        result = evaluate_bias_risk(flag_variants, handling, exposures)
        self.assertIsNone(result)

    def test_threshold_boundary_strictly_greater_than(self):
        # Exactly at threshold (1 / 1000 = 0.1%) should NOT trigger — uses strict `>`.
        result = evaluate_bias_risk(
            UNEVEN_2WAY, MultipleVariantHandling.EXCLUDE, {"control": 799, "test": 200, "$multiple": 1}
        )
        self.assertIsNone(result)

    def test_threshold_boundary_just_above(self):
        # 2 / 1000 = 0.2% — above the 0.1% threshold.
        result = evaluate_bias_risk(
            UNEVEN_2WAY, MultipleVariantHandling.EXCLUDE, {"control": 798, "test": 200, "$multiple": 2}
        )
        assert result is not None
        self.assertGreater(result.multiple_variant_percentage, MULTIPLE_VARIANT_BIAS_THRESHOLD)


def baseline(step_counts: list[int], exposures: int) -> ExperimentStatsBaseValidated:
    return ExperimentStatsBaseValidated(
        key="control",
        number_of_samples=exposures,
        sum=step_counts[-1] if step_counts else 0,
        sum_squares=step_counts[-1] if step_counts else 0,
        step_counts=step_counts,
    )


class TestEvaluateFunnelPowerRisk(TestCase):
    def test_narrow_middle_step_under_sample_size_is_flagged(self):
        # 3% of exposures reach step 2 and 2% complete: a 2% binomial needs ~17k exposures to
        # resolve a 30% relative change, and only 10k are in.
        result = evaluate_funnel_power_risk(baseline([5000, 150, 100], 5000), 10000, 2, 30)
        assert result is not None
        self.assertEqual(result.narrowest_step, 2)
        self.assertAlmostEqual(result.narrowest_step_percentage, 3.0)
        self.assertEqual(result.observed_exposures, 10000)
        self.assertGreater(result.recommended_sample_size, 10000)

    @parameterized.expand(
        [
            # Every step keeps most exposures — nothing narrow to warn about.
            ("wide_funnel", [10000, 9000, 8000], 10000, 20000),
            # Narrow, but with enough exposures to detect the effect anyway.
            ("narrow_but_powered", [5000, 150, 100], 5000, 200_000),
            # A single-step funnel has no step to be narrow before the final one.
            ("single_step", [200], 10000, 20000),
            ("no_step_counts", [], 10000, 20000),
            ("no_exposures", [0, 0], 0, 0),
            # Nobody completed the funnel: there's no conversion rate to size against.
            ("zero_conversions", [300, 0], 10000, 20000),
        ]
    )
    def test_returns_none_when_not_at_risk(self, _name, step_counts, exposures, total_exposures):
        result = evaluate_funnel_power_risk(baseline(step_counts, exposures), total_exposures, 2, 30)
        self.assertIsNone(result)
