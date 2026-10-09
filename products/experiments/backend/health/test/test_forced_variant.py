from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import ExperimentHealthFindingSeverity
from products.experiments.backend.health.checks.forced_variant import forced_variant_release_condition
from products.experiments.backend.health.context import HealthContext, parse_flag_state

EVEN_SPLIT = [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
SHIPPED_SPLIT = [{"key": "control", "rollout_percentage": 0}, {"key": "test", "rollout_percentage": 100}]
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
) -> HealthContext:
    return HealthContext(
        **status,
        is_paused=False,
        archived=False,
        flag=parse_flag_state(active=True, deleted=deleted, groups=groups, variants=variants, early_exit=early_exit),
        primary_metric_count=1,
        secondary_metric_count=0,
        exposures=None,
    )


class TestForcedVariantReleaseCondition(TestCase):
    @parameterized.expand(
        [
            ("no_override", _context([EVERYONE]), None),
            (
                "qa_override_before_randomized_set",
                _context([{**STAFF, "variant": "test"}, EVERYONE]),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.INFO, "1", "test"),
            ),
            (
                "draft_qa_override",
                _context([{**STAFF, "variant": "test"}, EVERYONE], status=DRAFT),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.INFO, "1", "test"),
            ),
            (
                "catch_all_override",
                _context([{**EVERYONE, "variant": "control"}]),
                ("all_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1", "control"),
            ),
            (
                "catch_all_override_without_rollout",
                _context([{"properties": [], "variant": "test"}]),
                ("all_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1", "test"),
            ),
            (
                "cohorts_forced_into_both_variants",
                _context([{**IOS, "variant": "test"}, {**STAFF, "variant": "control"}]),
                ("all_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1, 2", "test, control"),
            ),
            (
                "randomized_set_at_zero_rollout_randomizes_nobody",
                _context([{**IOS, "variant": "test"}, {**EVERYONE, "rollout_percentage": 0}]),
                ("all_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1", "test"),
            ),
            (
                "override_at_zero_rollout",
                _context([{**STAFF, "variant": "test", "rollout_percentage": 0}, EVERYONE]),
                None,
            ),
            ("override_after_a_catch_all_is_unreachable", _context([EVERYONE, {**STAFF, "variant": "test"}]), None),
            (
                "override_after_a_group_catch_all_in_a_mixed_flag",
                _context([{**EVERYONE, "aggregation_group_type_index": 0}, {**STAFF, "variant": "test"}]),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.INFO, "2", "test"),
            ),
            (
                "override_after_a_catch_all_of_the_same_group_type",
                _context(
                    [
                        {**EVERYONE, "aggregation_group_type_index": 0, "variant": "test"},
                        {**EVERYONE, "aggregation_group_type_index": 0},
                        {**STAFF, "variant": "control"},
                    ]
                ),
                ("all_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1, 3", "test, control"),
            ),
            (
                "override_after_a_zero_catch_all_with_early_exit",
                _context([{**EVERYONE, "rollout_percentage": 0}, {**EVERYONE, "variant": "control"}], early_exit=True),
                None,
            ),
            (
                "override_after_a_partial_catch_all_with_early_exit",
                _context([{**EVERYONE, "rollout_percentage": 50}, {**STAFF, "variant": "test"}], early_exit=True),
                None,
            ),
            (
                "override_after_a_partial_catch_all",
                _context([{**EVERYONE, "rollout_percentage": 50}, {**STAFF, "variant": "test"}]),
                ("some_conditions_pinned", ExperimentHealthFindingSeverity.INFO, "2", "test"),
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
                ("all_conditions_pinned", ExperimentHealthFindingSeverity.WARNING, "1", "control"),
            ),
            ("ended", _context([{**EVERYONE, "variant": "control"}], status=ENDED), None),
            ("deleted_flag", _context([{**EVERYONE, "variant": "control"}], deleted=True), None),
        ]
    )
    def test_forced_variant_release_condition(
        self,
        _name: str,
        ctx: HealthContext,
        expected: tuple[str, ExperimentHealthFindingSeverity, str, str] | None,
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
            ),
            expected,
        )
        self.assertEqual("before launch" in finding.detail, not ctx.is_launched)
