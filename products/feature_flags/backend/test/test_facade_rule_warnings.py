import json
from copy import deepcopy
from decimal import Decimal
from typing import Any, get_args

import pytest

from jsonschema import Draft202012Validator
from parameterized import parameterized

from products.feature_flags.backend.facade.config_validation import (
    ConfigValidationError,
    Predicate,
    ValidatedConfig,
    ValidatedRule,
)
from products.feature_flags.backend.facade.rule_warnings import (
    ConfigReview,
    config_warnings,
    reorder_warnings,
    review_config,
)
from products.feature_flags.backend.facade.warnings import (
    ManagementWarning,
    ManagementWarningCode,
    serialize_management_warning,
)
from products.feature_flags.backend.test.test_facade_config_validation import LIMITS, load_contract

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
D = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
SEED = "release-preview"
OTHER_SEED = "second-seed"

PRO = Predicate(key="plan", operator="exact", value='"pro"', negation=False)
FREE = Predicate(key="plan", operator="exact", value='"free"', negation=False)
NORWAY = Predicate(key="country", operator="exact", value='"NO"', negation=False)


def targeted(rule_id: str, value: bool = True, *predicates: Predicate) -> ValidatedRule:
    return ValidatedRule(id=rule_id, rule_type="targeted_release", predicates=frozenset(predicates), value=value)


def rollout(
    rule_id: str,
    percentage: int | float | str,
    value: bool = True,
    *predicates: Predicate,
    seed: str = SEED,
    miss: str = "continue",
) -> ValidatedRule:
    return ValidatedRule(
        id=rule_id,
        rule_type="percentage_rollout",
        predicates=frozenset(predicates),
        value=value,
        rollout_percentage=Decimal(str(percentage)),
        on_rollout_miss=miss,  # type: ignore[arg-type]
        seed=seed,
    )


def cfg(*rules: ValidatedRule, default: bool | None = False) -> ValidatedConfig:
    return ValidatedConfig(default_value=default, rules=rules)


def codes(warnings: tuple[ManagementWarning, ...]) -> list[tuple[str, str | None]]:
    return [(warning.code, warning.attr) for warning in warnings]


def text(warning: ManagementWarning) -> str:
    assert warning.detail is not None
    return warning.detail


UNREACHABLE = "UNREACHABLE_LOWER_RULE"
EXTENDS = "ROLLOUT_MISS_CAN_ENTER_LOWER_RULE"
REORDER = "RULE_ORDER_CHANGES_TRAFFIC"


class TestConfigWarnings:
    @parameterized.expand(
        [
            (
                "targeted_catch_all_blocks_lower",
                cfg(targeted(A), targeted(B, False)),
                [(UNREACHABLE, "filters.rules[1]")],
            ),
            (
                "return_default_catch_all_is_terminal",
                cfg(rollout(A, 25, miss="return_default"), targeted(B)),
                [(UNREACHABLE, "filters.rules[1]")],
            ),
            (
                "zero_percent_return_default_is_terminal",
                cfg(rollout(A, 0, miss="return_default"), targeted(B)),
                [(UNREACHABLE, "filters.rules[1]")],
            ),
            (
                "hundred_percent_continue_is_terminal",
                cfg(rollout(A, 100), rollout(B, 50, seed=OTHER_SEED)),
                [(UNREACHABLE, "filters.rules[1]")],
            ),
            (
                "wider_terminal_rule_blocks_narrower",
                cfg(targeted(A, True, PRO), targeted(B, False, PRO, NORWAY)),
                [(UNREACHABLE, "filters.rules[1]")],
            ),
            (
                "same_seed_rules_close_the_hash_space",
                cfg(rollout(A, 60), rollout(B, 40, False, seed=SEED, miss="return_default"), targeted(C)),
                [(UNREACHABLE, "filters.rules[2]")],
            ),
            (
                "every_lower_rule_is_reported",
                cfg(targeted(A), targeted(B), targeted(C, False)),
                [(UNREACHABLE, "filters.rules[1]"), (UNREACHABLE, "filters.rules[2]")],
            ),
            ("continuing_partial_rollout_is_not_terminal", cfg(rollout(A, 99, False), targeted(B)), []),
            ("conditional_rule_is_not_a_catch_all", cfg(targeted(A, True, PRO), targeted(B, False)), []),
            (
                "narrower_terminal_rule_does_not_block_wider",
                cfg(targeted(A, True, PRO, NORWAY), targeted(B, False, PRO)),
                [],
            ),
            (
                "same_seed_no_op_rule_keeps_lower_reachable",
                cfg(rollout(A, 50), rollout(B, 50, False), targeted(C, False)),
                [],
            ),
            ("zero_percent_continue_is_a_no_op", cfg(rollout(A, 0), targeted(B)), []),
        ]
    )
    def test_unreachable_lower_rule(self, _name: str, config: ValidatedConfig, expected: list[tuple[str, str]]) -> None:
        assert codes(config_warnings(config)) == expected

    def test_unreachable_warning_identifies_the_blocking_rule(self) -> None:
        (warning,) = config_warnings(cfg(rollout(A, 50, False), targeted(B), targeted(C)))
        assert warning.attr == "filters.rules[2]"
        assert C in text(warning) and B in text(warning) and A not in text(warning)

    @parameterized.expand(
        [
            ("catch_all_true_after_partial_true", cfg(rollout(A, 25), targeted(B)), [(EXTENDS, "filters.rules[1]")]),
            (
                "other_seed_percentage_extends",
                cfg(rollout(A, 25), rollout(B, 50, seed=OTHER_SEED)),
                [(EXTENDS, "filters.rules[1]")],
            ),
            (
                "same_seed_higher_percentage_extends",
                cfg(rollout(A, 25), rollout(B, 50)),
                [(EXTENDS, "filters.rules[1]")],
            ),
            (
                "two_decimal_boundary_extends",
                cfg(rollout(A, "33.33"), rollout(B, "33.34")),
                [(EXTENDS, "filters.rules[1]")],
            ),
            (
                "narrower_lower_rule_overlaps",
                cfg(rollout(A, 25), targeted(B, True, PRO)),
                [(EXTENDS, "filters.rules[1]")],
            ),
            ("wider_lower_rule_overlaps", cfg(rollout(A, 25, True, PRO), targeted(B)), [(EXTENDS, "filters.rules[1]")]),
            (
                "continuing_intervening_rule_does_not_block",
                cfg(rollout(A, 25), rollout(B, 50, False, seed=OTHER_SEED), targeted(C)),
                [(EXTENDS, "filters.rules[2]")],
            ),
            (
                "unrelated_intervening_terminal_rule_is_inconclusive",
                cfg(rollout(A, 25), targeted(B, False, FREE), targeted(C, True, PRO)),
                [],
            ),
            (
                "each_extending_pair_is_reported_once",
                cfg(rollout(A, 25), targeted(B), targeted(C)),
                [(UNREACHABLE, "filters.rules[2]"), (EXTENDS, "filters.rules[1]")],
            ),
            ("lower_rule_serves_another_value", cfg(rollout(A, 25), targeted(B, False)), []),
            ("same_seed_equal_percentage_cannot_extend", cfg(rollout(A, 25), rollout(B, 25)), []),
            ("same_seed_lower_percentage_cannot_extend", cfg(rollout(A, 25), rollout(B, 10)), []),
            ("same_seed_equal_two_decimal_boundary", cfg(rollout(A, "33.33"), rollout(B, "33.33")), []),
            ("zero_percent_lower_rule_serves_nobody", cfg(rollout(A, 25), rollout(B, 0, seed=OTHER_SEED)), []),
            (
                "terminal_miss_never_continues",
                cfg(rollout(A, 25, miss="return_default"), targeted(B)),
                [(UNREACHABLE, "filters.rules[1]")],
            ),
            ("full_rollout_never_misses", cfg(rollout(A, 100), targeted(B)), [(UNREACHABLE, "filters.rules[1]")]),
            ("zero_rollout_serves_nobody_to_extend", cfg(rollout(A, 0), targeted(B)), []),
            (
                "terminal_catch_all_between_blocks",
                cfg(rollout(A, 25), targeted(B, False), targeted(C)),
                [(UNREACHABLE, "filters.rules[2]")],
            ),
            (
                "conditional_terminal_between_is_inconclusive",
                cfg(rollout(A, 25), targeted(B, False, PRO), targeted(C)),
                [],
            ),
            ("disjoint_targeting_is_inconclusive", cfg(rollout(A, 25, True, PRO), targeted(B, True, FREE)), []),
            (
                "upper_rule_emptied_by_same_seed_predecessor",
                cfg(rollout(A, 40, False), rollout(B, 30), targeted(C)),
                [],
            ),
            (
                "same_seed_predecessor_raises_the_reach_threshold",
                cfg(rollout(A, 25), rollout(B, 60, False), rollout(C, 50)),
                [],
            ),
        ]
    )
    def test_rollout_miss_can_enter_lower_rule(
        self, _name: str, config: ValidatedConfig, expected: list[tuple[str, str]]
    ) -> None:
        assert codes(config_warnings(config)) == expected

    def test_rollout_miss_warning_explains_the_reach_without_the_seed(self) -> None:
        (warning,) = config_warnings(cfg(rollout(A, "33.3"), targeted(B)))
        assert warning.attr == "filters.rules[1]"
        assert A in text(warning) and B in text(warning) and "33.3%" in text(warning)
        assert SEED not in text(warning)

    @parameterized.expand(
        [
            ("single_rule", cfg(rollout(A, 25))),
            ("different_values_compose", cfg(rollout(A, 25), rollout(B, 25, False, seed=OTHER_SEED))),
            (
                "equal_valued_terminal_rules_after_a_partial_false",
                cfg(rollout(A, 25, False), targeted(B, True, PRO), targeted(C, True, FREE)),
            ),
            ("null_default", cfg(rollout(A, 25, miss="return_default"), default=None)),
        ]
    )
    def test_ordinary_composition_produces_no_warning(self, _name: str, config: ValidatedConfig) -> None:
        assert config_warnings(config) == ()


class TestReorderWarnings:
    @parameterized.expand(
        [
            (
                "different_values_swap",
                cfg(targeted(A, True), targeted(B, False)),
                cfg(targeted(B, False), targeted(A, True)),
                [(REORDER, "filters.rules[0]")],
            ),
            (
                "conditional_false_moves_above_partial_true",
                cfg(rollout(A, 50), targeted(B, False, PRO)),
                cfg(targeted(B, False, PRO), rollout(A, 50)),
                [(REORDER, "filters.rules[0]")],
            ),
            (
                "terminal_miss_moves_above_targeted",
                cfg(targeted(A), rollout(B, 25, miss="return_default")),
                cfg(rollout(B, 25, miss="return_default"), targeted(A)),
                [(REORDER, "filters.rules[0]")],
            ),
            (
                "terminal_miss_with_null_default_moves_above_targeted",
                cfg(targeted(A), rollout(B, 25, miss="return_default"), default=None),
                cfg(rollout(B, 25, miss="return_default"), targeted(A), default=None),
                [(REORDER, "filters.rules[0]")],
            ),
            (
                "same_seed_different_percentages_and_values",
                cfg(rollout(A, 25, True), rollout(B, 50, False)),
                cfg(rollout(B, 50, False), rollout(A, 25, True)),
                [(REORDER, "filters.rules[0]")],
            ),
            (
                "swap_below_an_unchanged_partial_rule",
                cfg(rollout(C, 50, False), targeted(A, True), targeted(B, False)),
                cfg(rollout(C, 50, False), targeted(B, False), targeted(A, True)),
                [(REORDER, "filters.rules[1]")],
            ),
            ("identical_order", cfg(targeted(A), targeted(B, False)), cfg(targeted(A), targeted(B, False)), []),
            ("same_value_swap_is_a_no_op", cfg(targeted(A), targeted(B)), cfg(targeted(B), targeted(A)), []),
            (
                "continuing_partial_true_below_targeted_true_is_a_no_op",
                cfg(targeted(A), rollout(B, 25)),
                cfg(rollout(B, 25), targeted(A)),
                [],
            ),
            (
                "same_seed_same_percentage_same_value",
                cfg(rollout(A, 25), rollout(B, 25)),
                cfg(rollout(B, 25), rollout(A, 25)),
                [],
            ),
            (
                "terminal_miss_matching_the_default_is_a_no_op",
                cfg(targeted(A, False), rollout(B, 25, False, miss="return_default")),
                cfg(rollout(B, 25, False, miss="return_default"), targeted(A, False)),
                [],
            ),
            (
                "disjoint_targeting_is_inconclusive",
                cfg(targeted(A, True, PRO), targeted(B, False, FREE)),
                cfg(targeted(B, False, FREE), targeted(A, True, PRO)),
                [],
            ),
            (
                "blocked_by_an_unmoved_terminal_rule",
                cfg(targeted(C, False), targeted(A), targeted(B, False)),
                cfg(targeted(C, False), targeted(B, False), targeted(A)),
                [],
            ),
            ("added_rule_is_an_edit_not_a_reorder", cfg(targeted(A)), cfg(targeted(B, False), targeted(A)), []),
            (
                "edited_value_in_the_pair_is_an_edit_not_a_reorder",
                cfg(targeted(A), targeted(B)),
                cfg(targeted(B, False), targeted(A)),
                [],
            ),
            (
                "edited_targeting_in_the_pair_is_an_edit_not_a_reorder",
                cfg(targeted(A), targeted(B, False, PRO)),
                cfg(targeted(B, False, PRO), targeted(A, True, FREE)),
                [],
            ),
            (
                "edited_seed_in_the_pair_is_an_edit_not_a_reorder",
                cfg(rollout(A, 50), targeted(B, False)),
                cfg(targeted(B, False), rollout(A, 50, seed=OTHER_SEED)),
                [],
            ),
            ("removed_rule_is_an_edit_not_a_reorder", cfg(targeted(B, False), targeted(A)), cfg(targeted(A)), []),
        ]
    )
    def test_rule_order_changes_traffic(
        self, _name: str, current: ValidatedConfig, proposed: ValidatedConfig, expected: list[tuple[str, str]]
    ) -> None:
        assert codes(reorder_warnings(current, proposed)) == expected

    def test_reorder_warning_names_both_rules_and_is_deduplicated(self) -> None:
        # The same inverted pair is proven for two populations (everyone, and pro accounts) and reported once.
        current = cfg(targeted(A), targeted(B, False), targeted(D, False, PRO))
        proposed = cfg(targeted(B, False), targeted(A), targeted(D, False, PRO))
        warnings = reorder_warnings(current, proposed)
        assert codes(warnings) == [(REORDER, "filters.rules[0]")]
        assert A in text(warnings[0]) and B in text(warnings[0]) and D not in text(warnings[0])
        assert warnings == reorder_warnings(current, proposed)

    def test_reorder_below_a_blocking_rule_is_not_a_traffic_change(self) -> None:
        # A blocks B for pro accounts in both orders, so only the pair with the catch-all is reported.
        current = cfg(targeted(A, True, PRO), targeted(B, False, PRO), targeted(C, False))
        proposed = cfg(targeted(C, False), targeted(B, False, PRO), targeted(A, True, PRO))
        (warning,) = reorder_warnings(current, proposed)
        assert warning.attr == "filters.rules[0]"
        assert A in text(warning) and C in text(warning) and B not in text(warning)


ROLLOUT_DOCUMENT: dict[str, Any] = {
    "version": 2,
    "return_type": "boolean",
    "default_value": False,
    "rules": [
        {
            "id": A,
            "rule_type": "percentage_rollout",
            "targeting": {"properties": []},
            "value": True,
            "rollout_percentage": 25,
            "on_rollout_miss": "continue",
            "assignment_algorithm": "sha1_60_v1",
            "seed": SEED,
        },
        {"id": B, "rule_type": "targeted_release", "targeting": {"properties": []}, "value": True},
        {"id": C, "rule_type": "targeted_release", "targeting": {"properties": []}, "value": False},
    ],
}


class TestReviewConfig:
    def test_validates_then_reports_configuration_warnings(self) -> None:
        document = deepcopy(ROLLOUT_DOCUMENT)
        review = review_config(document, limits=LIMITS)
        assert isinstance(review, ConfigReview)
        assert [rule.id for rule in review.config.rules] == [A, B, C]
        assert codes(review.warnings) == [(UNREACHABLE, "filters.rules[2]"), (EXTENDS, "filters.rules[1]")]
        assert document == ROLLOUT_DOCUMENT
        assert review == review_config(document, limits=LIMITS)

    def test_without_the_stored_config_no_reorder_is_claimed(self) -> None:
        review = review_config(
            {**ROLLOUT_DOCUMENT, "rules": [ROLLOUT_DOCUMENT["rules"][0], ROLLOUT_DOCUMENT["rules"][2]]}, limits=LIMITS
        )
        assert review.warnings == ()

    def test_reorder_is_compared_against_the_stored_config(self) -> None:
        current = review_config(ROLLOUT_DOCUMENT, limits=LIMITS).config
        reordered = {**ROLLOUT_DOCUMENT, "rules": [ROLLOUT_DOCUMENT["rules"][2], *ROLLOUT_DOCUMENT["rules"][:2]]}
        review = review_config(reordered, limits=LIMITS, current=current)
        assert codes(review.warnings) == [
            (UNREACHABLE, "filters.rules[1]"),
            (UNREACHABLE, "filters.rules[2]"),
            (REORDER, "filters.rules[0]"),
            (REORDER, "filters.rules[0]"),
        ]
        assert [text(warning).startswith(f"Moving rule {C} above rule ") for warning in review.warnings[2:]] == [
            True,
            True,
        ]

    def test_invalid_candidate_raises_before_any_warning(self) -> None:
        with pytest.raises(ConfigValidationError):
            review_config({**ROLLOUT_DOCUMENT, "default_value": 0}, limits=LIMITS)


class TestWarningWire:
    def test_detector_warnings_serialize_against_the_released_schema_without_seeds(self) -> None:
        current = review_config(ROLLOUT_DOCUMENT, limits=LIMITS).config
        reordered = {**ROLLOUT_DOCUMENT, "rules": list(reversed(ROLLOUT_DOCUMENT["rules"]))}
        warnings = review_config(reordered, limits=LIMITS, current=current).warnings
        assert {warning.code for warning in warnings} == {UNREACHABLE, REORDER}
        schema = load_contract("schemas/management_warning.schema.json")
        assert set(schema["properties"]["code"]["enum"]) == set(get_args(ManagementWarningCode))
        validator = Draft202012Validator(schema)
        for warning in warnings:
            wire = serialize_management_warning(warning)
            assert set(wire) == {"code", "detail", "attr"}
            assert not list(validator.iter_errors(wire))
            assert SEED not in json.dumps(wire)
