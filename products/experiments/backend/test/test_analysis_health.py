from unittest import TestCase

from parameterized import parameterized

from posthog.schema import BiasRisk, MultipleVariantHandling, SrmCause

from products.experiments.backend.analysis_health import (
    MULTIPLE_VARIANT_BIAS_THRESHOLD,
    SurfaceExposureSplit,
    evaluate_bias_risk,
    evaluate_srm_diagnosis,
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


HEALTHY_EXPECTED = {"control": 5000.0, "test": 5000.0}
SMALL_EXPECTED = {"control": 250.0, "test": 250.0}


def surface(name: str, exposures: int, dominant_exposures: int, dominant_variant: str = "test"):
    return SurfaceExposureSplit(
        surface=name,
        exposures=exposures,
        dominant_variant=dominant_variant,
        dominant_exposures=dominant_exposures,
    )


class TestEvaluateSrmDiagnosis(TestCase):
    @parameterized.expand([("just_above", 0.001), ("well_above", 0.4)])
    def test_returns_none_when_not_significant(self, _name, p_value):
        self.assertIsNone(evaluate_srm_diagnosis(p_value=p_value, expected_counts=HEALTHY_EXPECTED))

    def test_small_sample_is_reported_as_low_sample_size(self):
        result = evaluate_srm_diagnosis(p_value=1e-5, expected_counts=SMALL_EXPECTED)
        assert result is not None
        self.assertEqual(result.cause, SrmCause.LOW_SAMPLE_SIZE)
        self.assertEqual(result.smallest_expected_count, 250.0)

    def test_low_sample_size_wins_before_any_surface_is_read(self):
        # The runner only pays for the surface scan once this pass comes back UNKNOWN.
        result = evaluate_srm_diagnosis(
            p_value=1e-5,
            expected_counts=SMALL_EXPECTED,
            surface_splits=[surface("/checkout", 400, 400), surface("/", 400, 200)],
        )
        assert result is not None
        self.assertEqual(result.cause, SrmCause.LOW_SAMPLE_SIZE)

    def test_one_single_variant_surface_alongside_a_balanced_one_is_capture_by_surface(self):
        result = evaluate_srm_diagnosis(
            p_value=1e-9,
            expected_counts=HEALTHY_EXPECTED,
            surface_splits=[surface("/", 8000, 4050), surface("/checkout", 2000, 1980)],
        )
        assert result is not None
        self.assertEqual(result.cause, SrmCause.CAPTURE_BY_SURFACE)
        assert result.surface_skew is not None
        self.assertEqual(result.surface_skew.surface, "/checkout")
        self.assertEqual(result.surface_skew.variant, "test")
        self.assertEqual(result.surface_skew.exposures, 2000)
        self.assertAlmostEqual(result.surface_skew.variant_percentage, 99.0, places=5)
        self.assertAlmostEqual(result.surface_skew.expected_percentage, 50.0, places=5)

    def test_same_skew_on_every_surface_is_not_blamed_on_a_surface(self):
        # No surface carries the configured split, so the imbalance is upstream of capture.
        # Naming a page here would send the reader after a page that is not the cause.
        result = evaluate_srm_diagnosis(
            p_value=1e-9,
            expected_counts=HEALTHY_EXPECTED,
            surface_splits=[surface("/", 6000, 5400), surface("/pricing", 4000, 3600)],
        )
        assert result is not None
        self.assertEqual(result.cause, SrmCause.UNKNOWN)

    @parameterized.expand(
        [
            # A long-tail path is single-variant by chance, so it must not be named.
            ("below_exposure_floor", [surface("/", 9950, 5000), surface("/rare", 50, 50)]),
            # 3% of first exposures is too little to explain the experiment's split.
            ("below_share_floor", [surface("/", 9700, 4900), surface("/promo", 300, 300)]),
            ("no_surfaces_at_all", []),
        ]
    )
    def test_surfaces_that_explain_nothing_leave_the_cause_unknown(self, _name, surface_splits):
        result = evaluate_srm_diagnosis(p_value=1e-9, expected_counts=HEALTHY_EXPECTED, surface_splits=surface_splits)
        assert result is not None
        self.assertEqual(result.cause, SrmCause.UNKNOWN)

    def test_dominant_variant_below_its_own_share_is_not_a_balanced_surface(self):
        # Under 80/20, control at 50% on "/" is itself a skew toward test, so "/" cannot be the
        # balanced surface that licenses blaming "/checkout". Both surfaces lean the same way,
        # which puts the imbalance upstream of capture.
        result = evaluate_srm_diagnosis(
            p_value=1e-9,
            expected_counts={"control": 8000.0, "test": 2000.0},
            surface_splits=[
                surface("/", 8000, 4000, dominant_variant="control"),
                surface("/checkout", 2000, 2000, dominant_variant="test"),
            ],
        )
        assert result is not None
        self.assertEqual(result.cause, SrmCause.UNKNOWN)

    def test_surface_share_is_measured_against_all_exposures_not_the_returned_rows(self):
        # The query returns only the busiest surfaces, so "/promo" is 12% of the two rows here
        # but 4% of the 10,000 exposures the experiment actually has. It sits under the 5%
        # floor, so it cannot explain the split and must not be named.
        result = evaluate_srm_diagnosis(
            p_value=1e-9,
            expected_counts=HEALTHY_EXPECTED,
            surface_splits=[surface("/", 3000, 1500, dominant_variant="control"), surface("/promo", 400, 400)],
        )
        assert result is not None
        self.assertEqual(result.cause, SrmCause.UNKNOWN)

    def test_expected_share_comes_from_the_configured_rollout_not_an_even_split(self):
        # An 80/20 rollout expects 80% control on every page, so 82% is not a skew.
        result = evaluate_srm_diagnosis(
            p_value=1e-9,
            expected_counts={"control": 8000.0, "test": 2000.0},
            surface_splits=[surface("/", 10000, 8200, dominant_variant="control")],
        )
        assert result is not None
        self.assertEqual(result.cause, SrmCause.UNKNOWN)
