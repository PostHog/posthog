from unittest import TestCase

from parameterized import parameterized

from posthog.schema import BiasRisk, ExposureCoverage, MultipleVariantHandling

from products.experiments.backend.analysis_health import (
    EXPOSURE_COVERAGE_MINIMUM_CALLERS,
    MULTIPLE_VARIANT_BIAS_THRESHOLD,
    evaluate_bias_risk,
    evaluate_exposure_coverage,
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


class TestEvaluateExposureCoverage(TestCase):
    def test_errored_share_above_threshold_returns_coverage(self):
        result = evaluate_exposure_coverage(900, {"timeout": 80, "connection_error": 20})
        self.assertIsInstance(result, ExposureCoverage)
        assert result is not None
        self.assertEqual(result.evaluated_entities, 900)
        self.assertEqual(result.errored_entities, 100)
        self.assertAlmostEqual(result.errored_percentage, 10.0, places=5)

    def test_error_reasons_are_ordered_largest_first(self):
        result = evaluate_exposure_coverage(900, {"flag_missing": 10, "timeout": 80, "connection_error": 20})
        assert result is not None
        self.assertEqual(list(result.error_reasons), ["timeout", "connection_error", "flag_missing"])

    def test_zero_count_reasons_are_dropped(self):
        result = evaluate_exposure_coverage(900, {"timeout": 100, "flag_missing": 0})
        assert result is not None
        self.assertEqual(result.error_reasons, {"timeout": 100})

    @parameterized.expand(
        [
            ("no_errors", 900, {}),
            ("errored_share_at_threshold", 9900, {"timeout": 100}),
            ("sample_below_minimum", 90, {"timeout": 5}),
            ("no_callers_at_all", 0, {}),
        ]
    )
    def test_returns_none_when_not_at_risk(self, _name, evaluated, errors):
        self.assertIsNone(evaluate_exposure_coverage(evaluated, errors))

    def test_minimum_callers_counts_errored_entities_too(self):
        # An all-errored population still has to clear the sample floor before it reports.
        below = EXPOSURE_COVERAGE_MINIMUM_CALLERS - 1
        self.assertIsNone(evaluate_exposure_coverage(0, {"timeout": below}))

        result = evaluate_exposure_coverage(0, {"timeout": EXPOSURE_COVERAGE_MINIMUM_CALLERS})
        assert result is not None
        self.assertAlmostEqual(result.errored_percentage, 100.0, places=5)
