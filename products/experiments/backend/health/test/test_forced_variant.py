from datetime import UTC, datetime
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import ExperimentHealthFindingSeverity
from products.experiments.backend.health.checks.forced_variant import (
    forced_variant_release_condition,
    needs_condition_set_traffic,
)
from products.experiments.backend.health.context import ConditionSetTraffic, HealthContext, parse_flag_state

EVEN_SPLIT = [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
SHIPPED_SPLIT = [{"key": "control", "rollout_percentage": 0}, {"key": "test", "rollout_percentage": 100}]
SPLIT_WITH_HOLDOUT = [*EVEN_SPLIT, {"key": "holdout", "rollout_percentage": 0}]
EVERYONE: dict[str, Any] = {"properties": [], "rollout_percentage": 100}
STAFF: dict[str, Any] = {
    "properties": [{"key": "email", "value": "@example.com", "operator": "icontains", "type": "person"}],
    "rollout_percentage": 100,
}
IOS: dict[str, Any] = {
    "properties": [{"key": "$device_type", "value": "iOS", "operator": "exact", "type": "person"}],
    "rollout_percentage": 100,
}

RUNNING = {"is_launched": True, "is_running": True, "has_ended": False}
ENDED = {"is_launched": True, "is_running": False, "has_ended": True}
DRAFT = {"is_launched": False, "is_running": False, "has_ended": False}


def _context(
    groups: list[dict[str, Any]],
    *,
    status: dict[str, bool] = RUNNING,
    variants: list[dict[str, Any]] = EVEN_SPLIT,
    deleted: bool = False,
    early_exit: bool = False,
    traffic: ConditionSetTraffic | None = None,
    excluded: frozenset[str] = frozenset(),
) -> HealthContext:
    return HealthContext(
        **status,
        is_paused=False,
        archived=False,
        flag=parse_flag_state(active=True, deleted=deleted, groups=groups, variants=variants, early_exit=early_exit),
        baseline_variant_key=None,
        primary_metric_count=1,
        secondary_metric_count=0,
        exposures=None,
        split_history=None,
        condition_set_traffic=traffic,
        excluded_variant_keys=excluded,
    )


def _traffic(people_by_set: dict[int, int], *, remotely_evaluated: float = 1.0) -> ConditionSetTraffic:
    calls = 2 * sum(people_by_set.values())
    return ConditionSetTraffic(
        since=datetime(2026, 10, 12, 13, 4, tzinfo=UTC),
        team_timezone="Europe/Berlin",
        people_by_set=people_by_set,
        calls=calls,
        remotely_evaluated_calls=round(calls * remotely_evaluated),
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
            ("ended", _context([{**EVERYONE, "variant": "control"}], status=ENDED), None),
            ("deleted_flag", _context([{**EVERYONE, "variant": "control"}], deleted=True), None),
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
        expected: tuple[str, ExperimentHealthFindingSeverity, str, str, float | None] | None,
    ) -> None:
        finding = forced_variant_release_condition(ctx)

        if expected is None:
            self.assertIsNone(finding)
            return
        assert finding is not None
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

        assert finding is not None
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
        ]
    )
    def test_needs_condition_set_traffic(self, _name: str, ctx: HealthContext, expected: bool) -> None:
        self.assertIs(needs_condition_set_traffic(ctx), expected)
