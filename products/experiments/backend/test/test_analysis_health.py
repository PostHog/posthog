from unittest import TestCase

from parameterized import parameterized

from posthog.schema import BiasRisk, MultipleVariantHandling

from products.experiments.backend.analysis_health import (
    MULTIPLE_VARIANT_BIAS_THRESHOLD,
    evaluate_bias_risk,
    srm_crosses_alert_threshold,
)

UNEVEN_2WAY = [{"rollout_percentage": 80}, {"rollout_percentage": 20}]
EVEN_2WAY = [{"rollout_percentage": 50}, {"rollout_percentage": 50}]


class TestEvaluateBiasRisk(TestCase):
    def test_observed_bias_returns_populated_risk(self):
        # 20 / (800 + 200 + 20) ≈ 1.96%, well above the 0.1% threshold.
        result = evaluate_bias_risk(
            UNEVEN_2WAY, MultipleVariantHandling.EXCLUDE, {"control": 800, "test": 200, "$multiple": 20}
        )
        self.assertIsInstance(result, BiasRisk)
        assert result is not None
        self.assertAlmostEqual(result.multiple_variant_percentage, 20 / 1020 * 100, places=5)

    def test_even_split_flags_high_multiple_share(self):
        # An even split does not clear the risk: EXCLUDE drops the non-random `$multiple`
        # population from both arms, so a high share still biases arm means.
        result = evaluate_bias_risk(
            EVEN_2WAY, MultipleVariantHandling.EXCLUDE, {"control": 500, "test": 500, "$multiple": 50}
        )
        self.assertIsInstance(result, BiasRisk)
        assert result is not None
        self.assertAlmostEqual(result.multiple_variant_percentage, 50 / 1050 * 100, places=5)

    @parameterized.expand(
        [
            (
                "first_seen_handling",
                UNEVEN_2WAY,
                MultipleVariantHandling.FIRST_SEEN,
                {"control": 800, "test": 200, "$multiple": 50},
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


class TestSrmCrossesAlertThreshold(TestCase):
    @parameterized.expand(
        [
            # Heavily skewed at high volume with a tiny p-value — the case the alert must fire on.
            (
                "skewed_high_volume",
                {"control": 6000, "test": 4000},
                {"control": 5000.0, "test": 5000.0},
                1e-9,
                True,
            ),
            # Same skew, but too few exposures to trust — below the 1,000 floor.
            (
                "skewed_below_min_exposures",
                {"control": 300, "test": 200},
                {"control": 250.0, "test": 250.0},
                1e-9,
                False,
            ),
            # Balanced split at high volume — observed matches expected, nothing to flag.
            (
                "balanced_high_volume",
                {"control": 5000, "test": 5000},
                {"control": 5000.0, "test": 5000.0},
                1.0,
                False,
            ),
            # p-value above the threshold — chi-squared not significant enough.
            (
                "p_value_above_threshold",
                {"control": 5300, "test": 4700},
                {"control": 5000.0, "test": 5000.0},
                0.01,
                False,
            ),
            # Tiny p-value but the observed share sits inside the 3σ band — variance, not SRM.
            (
                "within_three_sigma_band",
                {"control": 5075, "test": 4925},
                {"control": 5000.0, "test": 5000.0},
                1e-9,
                False,
            ),
            # No chi-squared result available.
            (
                "no_p_value",
                {"control": 6000, "test": 4000},
                {"control": 5000.0, "test": 5000.0},
                None,
                False,
            ),
        ]
    )
    def test_gate(self, _name, observed, expected, p_value, should_fire):
        self.assertEqual(
            srm_crosses_alert_threshold(observed=observed, expected=expected, p_value=p_value), should_fire
        )

    def test_multiple_variant_excluded_from_total(self):
        # The configured variants sum to 900 (below the 1,000 floor), so the gate must stay quiet.
        # A large `$multiple` count must not be counted toward the total to lift it over the floor.
        observed = {"control": 540, "test": 360, "$multiple": 5000}
        expected = {"control": 450.0, "test": 450.0}
        self.assertFalse(srm_crosses_alert_threshold(observed=observed, expected=expected, p_value=1e-9))
