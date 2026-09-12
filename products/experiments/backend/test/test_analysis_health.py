from unittest import TestCase

from parameterized import parameterized

from posthog.schema import BiasRisk, MultipleVariantHandling

from products.experiments.backend.analysis_health import (
    MULTIPLE_VARIANT_BIAS_THRESHOLD,
    evaluate_bias_risk,
    evaluate_daily_srm,
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


class TestEvaluateDailySrm(TestCase):
    def test_drift_hidden_by_healthy_totals_is_flagged(self):
        # Control runs hot for three days and cold for three days, so the totals
        # land at 300/300 and the cumulative chi-squared test sees nothing.
        daily_counts = {
            "control": {f"2024-01-0{day}": 90 for day in range(1, 4)} | {f"2024-01-0{day}": 10 for day in range(4, 7)},
            "test": {f"2024-01-0{day}": 10 for day in range(1, 4)} | {f"2024-01-0{day}": 90 for day in range(4, 7)},
        }
        result = evaluate_daily_srm(daily_counts, {"control": 50, "test": 50})
        assert result is not None
        self.assertLess(result.p_value, 0.001)
        # The premise of the test: the cumulative totals are identical, so only the daily test can see this
        self.assertEqual(sum(daily_counts["control"].values()), sum(daily_counts["test"].values()))

    def test_healthy_split_is_not_flagged(self):
        daily_counts = {
            "control": {"2024-01-01": 50, "2024-01-02": 52, "2024-01-03": 48},
            "test": {"2024-01-01": 50, "2024-01-02": 48, "2024-01-03": 52},
        }
        result = evaluate_daily_srm(daily_counts, {"control": 50, "test": 50})
        assert result is not None
        self.assertGreater(result.p_value, 0.05)

    def test_uneven_split_is_measured_against_its_own_rollout(self):
        daily_counts = {
            "control": {"2024-01-01": 800, "2024-01-02": 802},
            "test": {"2024-01-01": 200, "2024-01-02": 198},
        }
        result = evaluate_daily_srm(daily_counts, {"control": 80, "test": 20})
        assert result is not None
        self.assertGreater(result.p_value, 0.05)

    def test_bonferroni_correction_scales_with_the_days_tested(self):
        one_day = evaluate_daily_srm(
            {"control": {"2024-01-01": 60}, "test": {"2024-01-01": 40}},
            {"control": 50, "test": 50},
        )
        four_days = evaluate_daily_srm(
            {
                "control": {f"2024-01-0{day}": 60 for day in range(1, 5)},
                "test": {f"2024-01-0{day}": 40 for day in range(1, 5)},
            },
            {"control": 50, "test": 50},
        )
        assert one_day is not None and four_days is not None
        self.assertAlmostEqual(four_days.p_value, min(one_day.p_value * 4, 1.0), places=10)

    @parameterized.expand(
        [
            (
                "every_day_below_the_minimum",
                {"control": {"2024-01-01": 40}, "test": {"2024-01-01": 40}},
                {"control": 50.0, "test": 50.0},
            ),
            ("single_variant", {"control": {"2024-01-01": 400}}, {"control": 100.0}),
        ]
    )
    def test_returns_none_without_testable_data(self, _name, daily_counts, expected_ratios):
        self.assertIsNone(evaluate_daily_srm(daily_counts, expected_ratios))
