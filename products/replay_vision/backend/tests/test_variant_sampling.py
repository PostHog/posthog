import pytest

from posthog.hogql import ast

from products.replay_vision.backend.queries.scanner_candidate_query import (
    SAMPLE_RATE_PRECISION,
    variant_sampling_predicate,
)
from products.replay_vision.backend.queries.variant_sampling import plan_variant_sampling


class TestPlanVariantSampling:
    def test_uneven_split_gets_even_coverage_at_the_same_total(self) -> None:
        # The doc's example: 10% over a 90/10 split keeps ~50 of each per 1,000 exposed sessions,
        # not 90 and 10, and the total budget is unchanged.
        plan = plan_variant_sampling(0.1, {"control": 0.9, "test": 0.1}, None)

        assert plan is not None
        assert plan.rates["control"] == pytest.approx(0.05 / 0.9)
        assert plan.rates["test"] == pytest.approx(0.5)
        assert plan.effective_rate == pytest.approx(0.1)
        # Equal coverage: each variant contributes the same absolute fraction.
        assert plan.population_shares["control"] * plan.rates["control"] == pytest.approx(
            plan.population_shares["test"] * plan.rates["test"]
        )

    def test_a_capped_small_variant_frees_its_budget_for_the_others(self) -> None:
        # 95/5 at 20%: the small arm is sampled whole (rate 1) and cannot supply more, so the
        # leftover budget flows to control instead of shrinking the total.
        plan = plan_variant_sampling(0.2, {"control": 0.95, "test": 0.05}, None)

        assert plan is not None
        assert plan.rates["test"] == 1.0
        assert plan.rates["control"] == pytest.approx(0.15 / 0.95)
        assert plan.effective_rate == pytest.approx(0.2)

    def test_selected_variants_normalize_within_the_watched_set(self) -> None:
        plan = plan_variant_sampling(0.5, {"control": 0.5, "test": 0.4, "beta": 0.1}, ["control", "test"])

        assert plan is not None
        assert set(plan.rates) == {"control", "test"}
        assert plan.population_shares["control"] == pytest.approx(5 / 9)

    @pytest.mark.parametrize(
        "selected,shares",
        [
            (["test"], {"control": 0.5, "test": 0.5}),
            (None, {}),
        ],
    )
    def test_no_plan_when_balancing_changes_nothing(self, selected, shares) -> None:
        assert plan_variant_sampling(0.1, shares, selected) is None

    def test_a_zero_share_variant_is_sampled_whole_without_eating_budget(self) -> None:
        plan = plan_variant_sampling(0.1, {"control": 1.0, "test": 0.0}, None)

        assert plan is not None
        assert plan.rates["test"] == 1.0
        assert plan.rates["control"] == pytest.approx(0.1)


class TestVariantSamplingPredicate:
    def test_builds_one_threshold_arm_per_variant_over_the_shared_hash(self) -> None:
        predicate = variant_sampling_predicate({"control": 0.25, "test": 1.0}, "salt-1")

        assert isinstance(predicate, ast.Call) and predicate.name == "multiIf"
        # Two (condition, then) pairs plus the fall-through.
        assert len(predicate.args) == 5
        thresholds = [
            arg.right.value
            for arg in predicate.args[1::2]
            if isinstance(arg, ast.CompareOperation) and isinstance(arg.right, ast.Constant)
        ]
        assert thresholds == [round(0.25 * SAMPLE_RATE_PRECISION), SAMPLE_RATE_PRECISION]
        fall_through = predicate.args[-1]
        assert isinstance(fall_through, ast.Constant) and fall_through.value is False

    def test_no_predicate_when_every_variant_is_sampled_whole(self) -> None:
        assert variant_sampling_predicate({"control": 1.0, "test": 1.0}, "salt-1") is None
