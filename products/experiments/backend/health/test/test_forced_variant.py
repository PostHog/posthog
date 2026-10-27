from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import ExperimentHealthFinding, ExperimentHealthFindingSeverity
from products.experiments.backend.health.checks.forced_variant import forced_variant_release_condition
from products.experiments.backend.health.condition_set_traffic import grades_by_pinned_share
from products.experiments.backend.health.context import (
    ConditionSetTraffic,
    FlagHistory,
    FlagHistoryNotChecked,
    HealthContext,
    parse_flag_state,
)
from products.experiments.backend.health.skips import FLAG_DELETED, NOT_AFTER_END, CheckSkip, not_applicable
from products.experiments.backend.health.test.factories import (
    DRAFT,
    ENDED,
    RUNNING,
    RUNNING_CONTEXT,
    Status,
    flag_history,
)
from products.feature_flags.backend.facade.edits import ConditionsChange, parse_release_conditions

EVEN_SPLIT = [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
SHIPPED_SPLIT = [{"key": "control", "rollout_percentage": 0}, {"key": "test", "rollout_percentage": 100}]
SPLIT_WITH_HOLDOUT = [*EVEN_SPLIT, {"key": "holdout", "rollout_percentage": 0}]
EVERYONE: dict[str, Any] = {"properties": [], "rollout_percentage": 100}
STAFF: dict[str, Any] = {
    "properties": [{"key": "email", "value": "@example.com", "operator": "icontains", "type": "person"}],
    "rollout_percentage": 100,
}
STAFF_AT_ONE_DOMAIN: dict[str, Any] = {
    "properties": [{"key": "email", "value": "qa@example.com", "operator": "icontains", "type": "person"}],
    "rollout_percentage": 100,
}
IOS: dict[str, Any] = {
    "properties": [{"key": "$device_type", "value": "iOS", "operator": "exact", "type": "person"}],
    "rollout_percentage": 100,
}

CHANGED_AT = datetime(2026, 9, 12, 13, 4, tzinfo=UTC)


def _property_is(key: str, value: str, *, group_type_index: int | None = None) -> dict[str, Any]:
    source = {"type": "person"} if group_type_index is None else {"type": "group", "group_type_index": group_type_index}
    return {
        "properties": [{"key": key, "value": [value], "operator": "exact", **source}],
        "rollout_percentage": 100,
    }


def _context(
    groups: list[dict[str, Any]],
    *,
    status: Status = RUNNING,
    variants: list[dict[str, Any]] = EVEN_SPLIT,
    deleted: bool = False,
    early_exit: bool = False,
    traffic: ConditionSetTraffic | None = None,
    excluded: frozenset[str] = frozenset(),
    groups_at_launch: list[dict[str, Any]] | None = None,
) -> HealthContext:
    return replace(
        RUNNING_CONTEXT,
        **status,
        flag=parse_flag_state(active=True, deleted=deleted, groups=groups, variants=variants, early_exit=early_exit),
        flag_history=None if groups_at_launch is None else _history(groups_at_launch, groups, variants),
        condition_set_traffic=traffic,
        excluded_variant_keys=excluded,
    )


def _history(
    before: list[dict[str, Any]], after: list[dict[str, Any]], variants: list[dict[str, Any]]
) -> FlagHistory | FlagHistoryNotChecked:
    variant_keys = [variant["key"] for variant in variants]
    change = ConditionsChange(
        changed_at=CHANGED_AT,
        before=parse_release_conditions(before, variant_keys=variant_keys),
        after=parse_release_conditions(after, variant_keys=variant_keys),
    )
    return flag_history([change], launched_at=datetime(2026, 9, 12, 10, 0, tzinfo=UTC))


def _traffic(people_by_set: dict[int, int], *, remotely_evaluated: float = 1.0) -> ConditionSetTraffic:
    calls = 2 * sum(people_by_set.values())
    return ConditionSetTraffic(
        since=datetime(2026, 10, 12, 13, 4, tzinfo=UTC),
        team_timezone="Europe/Berlin",
        people_by_set=people_by_set,
        calls=calls,
        remotely_evaluated_calls=round(calls * remotely_evaluated),
        people_assigned_outside=0,
    )


class TestForcedVariantReleaseCondition(TestCase):
    @parameterized.expand(
        [
            ("no_override", _context([EVERYONE]), None),
            (
                "qa_override_before_randomized_set",
                _context([{**STAFF, "variant": "test"}, EVERYONE]),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.INFO, "1", "test", None),
            ),
            (
                "draft_qa_override",
                _context([{**STAFF, "variant": "test"}, EVERYONE], status=DRAFT),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.INFO, "1", "test", None),
            ),
            (
                "catch_all_override",
                _context([{**EVERYONE, "variant": "control"}]),
                ("all_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1", "control", None),
            ),
            (
                "cohorts_forced_into_both_variants",
                _context([{**IOS, "variant": "test"}, {**STAFF, "variant": "control"}]),
                ("all_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1, 2", "test, control", None),
            ),
            (
                "variants_mapped_from_a_property",
                _context(
                    [
                        {**_property_is("arm", "Control"), "variant": "control"},
                        {**_property_is("arm", "test"), "variant": "test"},
                    ]
                ),
                ("assigned_by_property", ExperimentHealthFindingSeverity.INFO, "1, 2", "control, test", None),
            ),
            (
                "segments_mapped_onto_variants",
                _context(
                    [
                        {**_property_is("plan", "free"), "variant": "control"},
                        {**_property_is("plan", "pro"), "variant": "test"},
                    ]
                ),
                ("all_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1, 2", "control, test", None),
            ),
            (
                "variants_mapped_from_a_person_and_a_group_property_of_one_key",
                _context(
                    [
                        {**_property_is("arm", "control"), "variant": "control"},
                        {**_property_is("arm", "test", group_type_index=0), "variant": "test"},
                    ]
                ),
                ("all_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1, 2", "control, test", None),
            ),
            (
                "one_variant_mapped_from_a_property",
                _context([{**_property_is("arm", "control"), "variant": "control"}]),
                ("all_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1", "control", None),
            ),
            (
                "variants_mapped_from_two_properties",
                _context(
                    [
                        {**_property_is("arm", "control"), "variant": "control"},
                        {**_property_is("cell", "test"), "variant": "test"},
                    ]
                ),
                ("all_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1, 2", "control, test", None),
            ),
            ("override_after_a_catch_all_is_unreachable", _context([EVERYONE, {**STAFF, "variant": "test"}]), None),
            (
                "override_after_a_partial_catch_all_with_early_exit",
                _context([{**EVERYONE, "rollout_percentage": 50}, {**STAFF, "variant": "test"}], early_exit=True),
                None,
            ),
            (
                "set_numbers_follow_the_flag_order",
                _context(
                    [{**STAFF, "variant": "test", "rollout_percentage": 0}, {**IOS, "variant": "control"}, EVERYONE]
                ),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.INFO, "2", "control", None),
            ),
            ("override_naming_no_variant_is_ignored", _context([{**STAFF, "variant": "old-test"}, EVERYONE]), None),
            (
                "shipped_variant_already_reported",
                _context([{**EVERYONE, "variant": "test"}], variants=SHIPPED_SPLIT),
                None,
            ),
            (
                "override_contradicts_the_shipped_variant",
                _context([{**EVERYONE, "variant": "control"}], variants=SHIPPED_SPLIT),
                ("all_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1", "control", None),
            ),
            ("ended", _context([{**EVERYONE, "variant": "control"}], status=ENDED), not_applicable(NOT_AFTER_END)),
            (
                "deleted_flag",
                _context([{**EVERYONE, "variant": "control"}], deleted=True),
                not_applicable(FLAG_DELETED),
            ),
            (
                "pinned_share_under_one_percent",
                _context([{**STAFF, "variant": "test"}, EVERYONE], traffic=_traffic({1: 5, 2: 995})),
                None,
            ),
            (
                "pinned_share_of_a_few_percent",
                _context([{**STAFF, "variant": "test"}, EVERYONE], traffic=_traffic({1: 15, 2: 985})),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.INFO, "1", "test", 0.0296),
            ),
            (
                "pinned_share_of_five_percent",
                _context([{**STAFF, "variant": "test"}, EVERYONE], traffic=_traffic({1: 50, 2: 1900})),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.INFO, "1", "test", 0.05),
            ),
            (
                "pinned_share_above_five_percent",
                _context([{**STAFF, "variant": "test"}, EVERYONE], traffic=_traffic({1: 120, 2: 880})),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1", "test", 0.2143),
            ),
            (
                "pins_to_two_variants_grade_by_the_most_affected",
                _context(
                    [{**STAFF, "variant": "control"}, {**IOS, "variant": "test"}, EVERYONE],
                    traffic=_traffic({1: 10, 2: 30, 3: 960}),
                ),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1, 2", "control, test", 0.0588),
            ),
            (
                "pins_to_a_small_variant",
                _context(
                    [{**STAFF, "variant": "test"}, EVERYONE],
                    variants=[{"key": "control", "rollout_percentage": 90}, {"key": "test", "rollout_percentage": 10}],
                    traffic=_traffic({1: 20, 2: 980}),
                ),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1", "test", 0.1695),
            ),
            (
                "too_few_people_to_measure",
                _context([{**STAFF, "variant": "test"}, EVERYONE], traffic=_traffic({1: 60, 2: 39})),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.INFO, "1", "test", None),
            ),
            (
                "small_share_from_too_few_remotely_evaluated_calls",
                _context(
                    [{**STAFF, "variant": "test"}, EVERYONE],
                    traffic=_traffic({1: 1, 2: 999}, remotely_evaluated=0.4),
                ),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.INFO, "1", "test", None),
            ),
            (
                "large_share_from_too_few_remotely_evaluated_calls",
                _context(
                    [{**STAFF, "variant": "test"}, EVERYONE],
                    traffic=_traffic({1: 120, 2: 880}, remotely_evaluated=0.4),
                ),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1", "test", 0.2143),
            ),
            (
                "pins_to_a_zero_percent_variant_the_analysis_shows",
                _context([{**STAFF, "variant": "holdout"}, EVERYONE], variants=SPLIT_WITH_HOLDOUT),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.INFO, "1", "holdout", None),
            ),
            (
                "pins_to_a_zero_percent_variant_the_analysis_excludes",
                _context(
                    [{**STAFF, "variant": "holdout"}, EVERYONE],
                    variants=SPLIT_WITH_HOLDOUT,
                    excluded=frozenset({"holdout"}),
                ),
                None,
            ),
            (
                "pins_to_a_variant_the_analysis_excludes",
                _context(
                    [{**STAFF, "variant": "test-2"}, EVERYONE],
                    variants=[*EVEN_SPLIT, {"key": "test-2", "rollout_percentage": 0}],
                    excluded=frozenset({"test-2"}),
                ),
                None,
            ),
            (
                "pins_to_a_zero_percent_variant_stay_out_of_the_share",
                _context(
                    [{**STAFF, "variant": "holdout"}, {**IOS, "variant": "test"}, EVERYONE],
                    variants=SPLIT_WITH_HOLDOUT,
                    traffic=_traffic({1: 500, 2: 30, 3: 470}),
                ),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1, 2", "holdout, test", 0.1132),
            ),
        ]
    )
    def test_forced_variant_release_condition(
        self,
        _name: str,
        ctx: HealthContext,
        expected: tuple[str, ExperimentHealthFindingSeverity, str, str, float | None] | CheckSkip | None,
    ) -> None:
        finding = forced_variant_release_condition(ctx)

        if not isinstance(finding, ExperimentHealthFinding) or not isinstance(expected, tuple):
            self.assertEqual(finding, expected)
            return
        self.assertEqual(
            (
                finding.subcode,
                finding.severity,
                finding.evidence["pinned_condition_sets"],
                finding.evidence["pinned_variant_keys"],
                finding.evidence.get("pinned_share"),
            ),
            expected,
        )
        self.assertEqual("before launch" in finding.detail, not ctx.is_launched)
        self.assertEqual("of the users who got" in finding.detail, expected[4] is not None)
        self.assertEqual('Nobody gets "holdout" at random' in finding.detail, "holdout" in expected[3])

    @parameterized.expand(
        [
            ("not_measured", _context([{**STAFF, "variant": "test"}, EVERYONE]), "not_measured", False),
            (
                "too_few_people",
                _context([{**STAFF, "variant": "test"}, EVERYONE], traffic=_traffic({1: 60, 2: 39})),
                "too_few_people",
                False,
            ),
            (
                "evaluated_outside_flag_service",
                _context(
                    [{**STAFF, "variant": "test"}, EVERYONE],
                    traffic=_traffic({1: 1, 2: 999}, remotely_evaluated=0.4),
                ),
                "evaluated_outside_flag_service",
                True,
            ),
            (
                "measured",
                _context([{**STAFF, "variant": "test"}, EVERYONE], traffic=_traffic({1: 30, 2: 970})),
                None,
                False,
            ),
            ("draft", _context([{**STAFF, "variant": "test"}, EVERYONE], status=DRAFT), None, False),
        ]
    )
    def test_an_unknown_share_names_its_reason(
        self, _name: str, ctx: HealthContext, expected_reason: str | None, says_not_measurable: bool
    ) -> None:
        finding = forced_variant_release_condition(ctx)

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(
            (finding.evidence.get("reason"), "can't measure" in finding.detail), (expected_reason, says_not_measurable)
        )

    @parameterized.expand(
        [
            ("some_conditions_pinned", _context([{**STAFF, "variant": "test"}, EVERYONE]), True),
            ("draft", _context([{**STAFF, "variant": "test"}, EVERYONE], status=DRAFT), False),
            ("all_conditions_pinned", _context([{**STAFF, "variant": "test"}, {**IOS, "variant": "control"}]), False),
            (
                "pins_to_a_zero_percent_variant_only",
                _context([{**STAFF, "variant": "holdout"}, EVERYONE], variants=SPLIT_WITH_HOLDOUT),
                False,
            ),
            (
                "an_override_removed_after_launch",
                _context([STAFF, EVERYONE], groups_at_launch=[{**STAFF, "variant": "test"}, EVERYONE]),
                True,
            ),
        ]
    )
    def test_grades_by_pinned_share(self, _name: str, ctx: HealthContext, expected: bool) -> None:
        self.assertIs(grades_by_pinned_share(ctx), expected)

    @parameterized.expand(
        [
            ("set_after_launch", [STAFF, EVERYONE], True),
            ("changed_after_launch", [{**STAFF, "variant": "control"}, EVERYONE], True),
            ("in_place_at_launch", [{**STAFF, "variant": "test"}, EVERYONE, IOS], False),
            ("filters_edited_after_launch", [{**STAFF_AT_ONE_DOMAIN, "variant": "test"}, EVERYONE], False),
        ]
    )
    def test_an_override_set_after_launch_carries_its_date(
        self, _name: str, groups_at_launch: list[dict[str, Any]], set_after_launch: bool
    ) -> None:
        finding = forced_variant_release_condition(
            _context([{**STAFF, "variant": "test"}, EVERYONE], groups_at_launch=groups_at_launch)
        )

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(
            "The override of Set 1 was set on September 12, 2026 at 3:04 PM CEST, after launch, so users it matches "
            "who were exposed before may have switched variants." in finding.detail,
            set_after_launch,
        )
        self.assertTrue(
            finding.detail.endswith(
                "Then move the experiment's start date to after the removal."
                if set_after_launch
                else "Then reset the experiment, or move its start date to after the removal."
            )
        )

    def test_variants_mapped_from_a_property_say_who_assigns_them(self) -> None:
        finding = forced_variant_release_condition(
            _context(
                [
                    {**_property_is("checkout_arm", "control"), "variant": "control"},
                    {**_property_is("checkout_arm", "test"), "variant": "test"},
                ]
            )
        )

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(
            (finding.title, finding.detail, finding.evidence["variant_property"]),
            (
                "Variants are assigned outside PostHog",
                'Each release condition that includes users matches the users whose property "checkout_arm" holds a '
                'variant key, and serves them that variant. So the code that sets "checkout_arm" assigns the '
                "variants, not PostHog. If it assigns at random, each variant gets similar users. If it assigns by "
                "who the users are, for example by plan or country, a difference in the results can come from those "
                "users and not from the variant.",
                "checkout_arm",
            ),
        )
