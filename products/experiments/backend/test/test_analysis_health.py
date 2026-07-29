from unittest import TestCase

from parameterized import parameterized

from posthog.schema import BiasRisk, MultipleVariantHandling

from products.experiments.backend.analysis_health import (
    MULTIPLE_VARIANT_BIAS_THRESHOLD,
    evaluate_bias_risk,
    evaluate_exposure_source_risk,
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


class TestEvaluateExposureSourceRisk(TestCase):
    def test_server_side_share_is_measured_against_all_exposures(self):
        # 300 server-side of 1000 total = 30%. The share must use the full exposed population as
        # the denominator, and name the server-side libs largest first.
        result = evaluate_exposure_source_risk(
            {"web": 700, "posthog-python": 200, "posthog-node": 100},
        )
        assert result is not None
        self.assertAlmostEqual(result.server_side_percentage, 30.0, places=5)
        self.assertEqual(result.libs, ["posthog-python", "posthog-node"])

    @parameterized.expand(
        [
            # Unrecognized and mobile libs must never count as server-side, or every experiment
            # running on a client SDK we don't have in the allowlist would warn.
            ("only_client_libs", {"web": 800, "posthog-ios": 150, "posthog-flutter": 100}),
            ("unknown_libs", {"web": 500, "some-custom-sdk": 400, "": 200}),
            # 50 / 1000 = 5%, under the 10% threshold.
            ("below_threshold", {"web": 950, "posthog-python": 50}),
            # Exactly 10% must not trigger — the check is a strict `>`.
            ("exactly_at_threshold", {"web": 900, "posthog-python": 100}),
            # Under the minimum sample the share is too noisy to act on, even at 100% server-side.
            ("below_minimum_sample", {"posthog-python": 99}),
            ("no_exposures", {}),
            ("server_lib_with_zero_count", {"web": 500, "posthog-go": 0}),
        ]
    )
    def test_returns_none_when_not_at_risk(self, _name, exposures_by_lib):
        self.assertIsNone(evaluate_exposure_source_risk(exposures_by_lib))
