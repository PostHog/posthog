from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.feature_flags.backend.exposure_change import (
    ExposureChangeKind,
    ExposureDirection,
    FlagExposureConfig,
    classify_exposure_change,
)
from products.feature_flags.backend.facade.config import ConfigFormatError

EMAIL = [{"key": "email", "type": "person", "operator": "icontains", "value": "@example.com"}]
OTHER_EMAIL = [{"key": "email", "type": "person", "operator": "icontains", "value": "@example.org"}]
SPLIT_50_50 = [{"key": "a", "rollout_percentage": 50}, {"key": "b", "rollout_percentage": 50}]
SPLIT_ALL_A = [{"key": "a", "rollout_percentage": 100}, {"key": "b", "rollout_percentage": 0}]
SPLIT_40_A = [{"key": "a", "rollout_percentage": 40}, {"key": "b", "rollout_percentage": 0}]

ENABLED = ExposureChangeKind.ENABLED
DISABLED = ExposureChangeKind.DISABLED
ROLLOUT_INCREASED = ExposureChangeKind.ROLLOUT_INCREASED
ROLLOUT_DECREASED = ExposureChangeKind.ROLLOUT_DECREASED
CONDITION_ADDED = ExposureChangeKind.CONDITION_ADDED
CONDITION_REMOVED = ExposureChangeKind.CONDITION_REMOVED
CRITERIA_CHANGED = ExposureChangeKind.CRITERIA_CHANGED
VARIANT_CHANGED = ExposureChangeKind.VARIANT_CHANGED
CONDITIONS_REORDERED = ExposureChangeKind.CONDITIONS_REORDERED
EARLY_EXIT_TURNED_OFF = ExposureChangeKind.EARLY_EXIT_TURNED_OFF
BUCKETING_CHANGED = ExposureChangeKind.BUCKETING_CHANGED
RAISES = ExposureDirection.RAISES
LOWERS = ExposureDirection.LOWERS
KEEPS = ExposureDirection.KEEPS


def _condition(
    rollout: float,
    properties: list[dict[str, Any]] | None = None,
    variant: str | None = None,
    aggregation: int | None = None,
) -> dict[str, Any]:
    condition: dict[str, Any] = {"properties": properties or [], "rollout_percentage": rollout, "variant": variant}
    if aggregation is not None:
        condition["aggregation_group_type_index"] = aggregation
    return condition


def _flag(
    *conditions: dict[str, Any],
    active: bool = True,
    deleted: bool = False,
    variants: list[dict[str, Any]] | None = None,
    aggregation: int | None = None,
    early_exit: bool = False,
    key: str = "flag",
    bucketing_identifier: str | None = None,
    ensure_experience_continuity: bool | None = False,
) -> FlagExposureConfig:
    filters: dict[str, Any] = {
        "groups": list(conditions),
        "aggregation_group_type_index": aggregation,
        "early_exit": early_exit,
    }
    if variants is not None:
        filters["multivariate"] = {"variants": variants}
    return FlagExposureConfig(
        active=active,
        deleted=deleted,
        filters=filters,
        key=key,
        bucketing_identifier=bucketing_identifier,
        ensure_experience_continuity=ensure_experience_continuity,
    )


VERSION_2 = FlagExposureConfig(
    active=True, filters={"version": 2}, key="flag", bucketing_identifier=None, ensure_experience_continuity=False
)


class TestClassifyExposureChange(TestCase):
    @parameterized.expand(
        [
            ("no_change", _flag(_condition(50)), _flag(_condition(50)), set(), KEEPS),
            (
                "edit_of_a_disabled_flag",
                _flag(_condition(10), active=False),
                _flag(_condition(100), active=False),
                set(),
                KEEPS,
            ),
            ("enabled", _flag(_condition(0), active=False), _flag(_condition(50)), {ENABLED}, RAISES),
            ("enabled_at_zero_rollout", _flag(_condition(0), active=False), _flag(_condition(0)), set(), KEEPS),
            ("disabled", _flag(_condition(50)), _flag(_condition(0), active=False), {DISABLED}, LOWERS),
            ("disabled_at_zero_rollout", _flag(_condition(0)), _flag(_condition(0), active=False), set(), KEEPS),
            ("restored", _flag(_condition(50), deleted=True), _flag(_condition(50)), {ENABLED}, RAISES),
            ("deleted", _flag(_condition(50)), _flag(_condition(50), deleted=True), {DISABLED}, LOWERS),
            ("rollout_increased", _flag(_condition(0)), _flag(_condition(50)), {ROLLOUT_INCREASED}, RAISES),
            ("rollout_decreased", _flag(_condition(50)), _flag(_condition(10)), {ROLLOUT_DECREASED}, LOWERS),
            (
                "condition_added",
                _flag(_condition(100, EMAIL)),
                _flag(_condition(100, EMAIL), _condition(20)),
                {CONDITION_ADDED},
                RAISES,
            ),
            (
                "condition_added_at_zero_rollout",
                _flag(_condition(100, EMAIL)),
                _flag(_condition(100, EMAIL), _condition(0)),
                set(),
                KEEPS,
            ),
            (
                "condition_removed_at_zero_rollout",
                _flag(_condition(0, EMAIL), _condition(100)),
                _flag(_condition(100)),
                set(),
                KEEPS,
            ),
            (
                "condition_at_zero_rollout_moved",
                _flag(
                    _condition(0, OTHER_EMAIL),
                    _condition(100, EMAIL, variant="a"),
                    _condition(100, variant="b"),
                    variants=SPLIT_50_50,
                ),
                _flag(
                    _condition(100, EMAIL, variant="a"),
                    _condition(100, variant="b"),
                    _condition(0, OTHER_EMAIL),
                    variants=SPLIT_50_50,
                ),
                set(),
                KEEPS,
            ),
            (
                "condition_removed",
                _flag(_condition(100, EMAIL), _condition(20)),
                _flag(_condition(100, EMAIL)),
                {CONDITION_REMOVED},
                LOWERS,
            ),
            (
                "properties_changed",
                _flag(_condition(100, EMAIL)),
                _flag(_condition(100, OTHER_EMAIL)),
                {CRITERIA_CHANGED},
                RAISES,
            ),
            (
                "properties_changed_on_a_condition_turned_off",
                _flag(_condition(50, EMAIL)),
                _flag(_condition(0, OTHER_EMAIL)),
                {ROLLOUT_DECREASED},
                LOWERS,
            ),
            (
                "flag_aggregation_changed",
                _flag(_condition(100)),
                _flag(_condition(100), aggregation=0),
                {CRITERIA_CHANGED},
                RAISES,
            ),
            (
                "flag_aggregation_changed_on_a_flag_that_serves_nobody",
                _flag(_condition(0)),
                _flag(_condition(0), aggregation=0),
                set(),
                KEEPS,
            ),
            (
                "split_changed",
                _flag(_condition(100), variants=SPLIT_50_50),
                _flag(
                    _condition(100),
                    variants=[{"key": "a", "rollout_percentage": 30}, {"key": "b", "rollout_percentage": 70}],
                ),
                {VARIANT_CHANGED},
                RAISES,
            ),
            (
                "split_changed_while_every_condition_has_an_override",
                _flag(_condition(100, variant="a"), variants=SPLIT_50_50),
                _flag(
                    _condition(100, variant="a"),
                    variants=[{"key": "a", "rollout_percentage": 30}, {"key": "b", "rollout_percentage": 70}],
                ),
                set(),
                KEEPS,
            ),
            (
                "multivariate_flag_made_boolean",
                _flag(_condition(100), variants=SPLIT_50_50),
                _flag(_condition(100)),
                {VARIANT_CHANGED},
                RAISES,
            ),
            (
                "override_added",
                _flag(_condition(100), variants=SPLIT_50_50),
                _flag(_condition(100, variant="b"), variants=SPLIT_50_50),
                {VARIANT_CHANGED},
                RAISES,
            ),
            (
                "override_changed_on_a_condition_turned_off",
                _flag(_condition(50, variant="b"), variants=SPLIT_50_50),
                _flag(_condition(0, variant="a"), variants=SPLIT_50_50),
                {ROLLOUT_DECREASED},
                LOWERS,
            ),
            (
                "rollout_lowered_on_a_multivariate_flag_without_overrides",
                _flag(_condition(50, EMAIL), _condition(100), variants=SPLIT_50_50),
                _flag(_condition(10, EMAIL), _condition(100), variants=SPLIT_50_50),
                {ROLLOUT_DECREASED},
                LOWERS,
            ),
            (
                "lowered_override_condition_falls_through_to_another_variant",
                _flag(_condition(100, EMAIL, variant="b"), _condition(100), variants=SPLIT_50_50),
                _flag(_condition(10, EMAIL, variant="b"), _condition(100), variants=SPLIT_50_50),
                {ROLLOUT_DECREASED},
                RAISES,
            ),
            (
                "lowered_override_condition_with_early_exit",
                _flag(_condition(100, EMAIL, variant="b"), _condition(100), variants=SPLIT_50_50, early_exit=True),
                _flag(_condition(10, EMAIL, variant="b"), _condition(100), variants=SPLIT_50_50, early_exit=True),
                {ROLLOUT_DECREASED},
                LOWERS,
            ),
            (
                "lowered_override_condition_with_early_exit_under_device_id_bucketing",
                _flag(
                    _condition(100, EMAIL, variant="b"),
                    _condition(100),
                    variants=SPLIT_50_50,
                    early_exit=True,
                    bucketing_identifier="device_id",
                ),
                _flag(
                    _condition(10, EMAIL, variant="b"),
                    _condition(100),
                    variants=SPLIT_50_50,
                    early_exit=True,
                    bucketing_identifier="device_id",
                ),
                {ROLLOUT_DECREASED},
                RAISES,
            ),
            (
                "removed_override_condition_falls_through_to_another_variant",
                _flag(_condition(100, EMAIL, variant="b"), _condition(100), variants=SPLIT_50_50),
                _flag(_condition(100), variants=SPLIT_50_50),
                {CONDITION_REMOVED},
                RAISES,
            ),
            (
                "condition_at_zero_rollout_removed_with_early_exit",
                _flag(_condition(0, EMAIL), _condition(100), early_exit=True),
                _flag(_condition(100), early_exit=True),
                {CONDITION_REMOVED},
                RAISES,
            ),
            (
                "properties_changed_on_a_condition_at_zero_rollout_with_early_exit",
                _flag(_condition(0, EMAIL), _condition(100), early_exit=True),
                _flag(_condition(0, OTHER_EMAIL), _condition(100), early_exit=True),
                {CRITERIA_CHANGED},
                RAISES,
            ),
            (
                "condition_at_zero_rollout_moved_with_early_exit",
                _flag(_condition(0, EMAIL), _condition(100), early_exit=True),
                _flag(_condition(100), _condition(0, EMAIL), early_exit=True),
                {CONDITIONS_REORDERED},
                RAISES,
            ),
            (
                "early_exit_turned_off",
                _flag(_condition(10, EMAIL), _condition(100), early_exit=True),
                _flag(_condition(10, EMAIL), _condition(100)),
                {EARLY_EXIT_TURNED_OFF},
                RAISES,
            ),
            (
                "early_exit_turned_off_with_a_lower_rollout",
                _flag(_condition(50, EMAIL), _condition(100), early_exit=True),
                _flag(_condition(10, EMAIL), _condition(100)),
                {EARLY_EXIT_TURNED_OFF, ROLLOUT_DECREASED},
                RAISES,
            ),
            (
                "early_exit_turned_off_at_full_rollout",
                _flag(_condition(100, EMAIL), _condition(100), early_exit=True),
                _flag(_condition(100, EMAIL), _condition(100)),
                set(),
                KEEPS,
            ),
            (
                "early_exit_turned_on",
                _flag(_condition(10, EMAIL), _condition(100)),
                _flag(_condition(10, EMAIL), _condition(100), early_exit=True),
                set(),
                KEEPS,
            ),
            (
                "group_condition_removed_before_a_person_condition",
                _flag(_condition(100, aggregation=0), _condition(100), variants=SPLIT_50_50),
                _flag(_condition(100), variants=SPLIT_50_50),
                {CONDITION_REMOVED},
                RAISES,
            ),
            (
                "group_and_person_conditions_reordered",
                _flag(_condition(100, aggregation=0), _condition(100), variants=SPLIT_50_50),
                _flag(_condition(100), _condition(100, aggregation=0), variants=SPLIT_50_50),
                {CONDITIONS_REORDERED},
                RAISES,
            ),
            (
                "group_and_person_conditions_of_a_boolean_flag_reordered",
                _flag(_condition(100, aggregation=0), _condition(100)),
                _flag(_condition(100), _condition(100, aggregation=0)),
                set(),
                KEEPS,
            ),
            (
                "conditions_with_different_overrides_reordered",
                _flag(_condition(100, EMAIL, variant="a"), _condition(100, variant="b"), variants=SPLIT_50_50),
                _flag(_condition(100, variant="b"), _condition(100, EMAIL, variant="a"), variants=SPLIT_50_50),
                {CONDITIONS_REORDERED},
                RAISES,
            ),
            (
                "conditions_of_a_boolean_flag_reordered",
                _flag(_condition(10, EMAIL), _condition(100)),
                _flag(_condition(100), _condition(10, EMAIL)),
                set(),
                KEEPS,
            ),
            (
                "conditions_reordered_with_early_exit",
                _flag(_condition(10, EMAIL), _condition(100), early_exit=True),
                _flag(_condition(100), _condition(10, EMAIL), early_exit=True),
                {CONDITIONS_REORDERED},
                RAISES,
            ),
            (
                "conditions_at_full_rollout_reordered_with_early_exit",
                _flag(_condition(100, EMAIL), _condition(100), early_exit=True),
                _flag(_condition(100), _condition(100, EMAIL), early_exit=True),
                set(),
                KEEPS,
            ),
            ("key_changed", _flag(_condition(50)), _flag(_condition(50), key="renamed"), {BUCKETING_CHANGED}, RAISES),
            (
                "key_changed_at_full_rollout",
                _flag(_condition(100)),
                _flag(_condition(100), key="renamed"),
                set(),
                KEEPS,
            ),
            (
                "key_changed_on_a_split",
                _flag(_condition(100), variants=SPLIT_50_50),
                _flag(_condition(100), variants=SPLIT_50_50, key="renamed"),
                {BUCKETING_CHANGED},
                RAISES,
            ),
            (
                "bucketing_identifier_changed",
                _flag(_condition(50)),
                _flag(_condition(50), bucketing_identifier="device_id"),
                {BUCKETING_CHANGED},
                RAISES,
            ),
            (
                "bucketing_identifier_changed_on_a_group_flag",
                _flag(_condition(50), aggregation=0),
                _flag(_condition(50), aggregation=0, bucketing_identifier="device_id"),
                set(),
                KEEPS,
            ),
            (
                "key_changed_on_a_group_flag",
                _flag(_condition(50), aggregation=0),
                _flag(_condition(50), aggregation=0, key="renamed"),
                {BUCKETING_CHANGED},
                RAISES,
            ),
            (
                "bucketing_identifier_written_as_the_default",
                _flag(_condition(50)),
                _flag(_condition(50), bucketing_identifier="distinct_id"),
                set(),
                KEEPS,
            ),
            (
                "experience_continuity_turned_on",
                _flag(_condition(50)),
                _flag(_condition(50), ensure_experience_continuity=True),
                {BUCKETING_CHANGED},
                RAISES,
            ),
            (
                "experience_continuity_turned_off",
                _flag(_condition(50), ensure_experience_continuity=True),
                _flag(_condition(50), ensure_experience_continuity=None),
                {BUCKETING_CHANGED},
                RAISES,
            ),
            (
                "experience_continuity_turned_on_under_device_id_bucketing",
                _flag(_condition(50), bucketing_identifier="device_id"),
                _flag(_condition(50), bucketing_identifier="device_id", ensure_experience_continuity=True),
                set(),
                KEEPS,
            ),
            (
                "experience_continuity_turned_on_for_a_person_condition_of_a_group_flag",
                _flag({**_condition(50), "aggregation_group_type_index": None}, aggregation=0),
                _flag(
                    {**_condition(50), "aggregation_group_type_index": None},
                    aggregation=0,
                    ensure_experience_continuity=True,
                ),
                set(),
                KEEPS,
            ),
            (
                "key_changed_on_a_partially_allocated_split",
                _flag(_condition(100), variants=SPLIT_40_A),
                _flag(_condition(100), variants=SPLIT_40_A, key="renamed"),
                {BUCKETING_CHANGED},
                RAISES,
            ),
            (
                "key_changed_with_a_condition_at_zero_rollout",
                _flag(_condition(0, EMAIL), _condition(100)),
                _flag(_condition(0, EMAIL), _condition(100), key="renamed"),
                set(),
                KEEPS,
            ),
            (
                "bucketing_identifier_changed_with_a_blocker_at_zero_rollout",
                _flag(_condition(0, EMAIL), _condition(100), early_exit=True),
                _flag(_condition(0, EMAIL), _condition(100), early_exit=True, bucketing_identifier="device_id"),
                {BUCKETING_CHANGED},
                RAISES,
            ),
            (
                "rollout_increased_and_condition_removed",
                _flag(_condition(10, EMAIL), _condition(20)),
                _flag(_condition(50, EMAIL)),
                {ROLLOUT_INCREASED, CONDITION_REMOVED},
                RAISES,
            ),
        ]
    )
    def test_classifies_the_edit(
        self,
        _name: str,
        before: FlagExposureConfig,
        after: FlagExposureConfig,
        kinds: set[ExposureChangeKind],
        direction: ExposureDirection,
    ) -> None:
        change = classify_exposure_change(before=before, after=after)

        assert change.kinds == kinds
        assert change.direction == direction

    @parameterized.expand(
        [
            (
                "split_and_overrides",
                _flag(_condition(100, EMAIL, variant="b"), _condition(100), variants=SPLIT_ALL_A),
                ("a", "b"),
            ),
            (
                "every_condition_has_an_override",
                _flag(_condition(100, EMAIL, variant="b"), variants=SPLIT_ALL_A),
                ("b",),
            ),
            ("variant_at_zero_percent", _flag(_condition(100), variants=SPLIT_ALL_A), ("a",)),
            (
                "override_of_a_condition_at_zero_rollout",
                _flag(_condition(0, EMAIL, variant="b"), _condition(100), variants=SPLIT_ALL_A),
                ("a",),
            ),
            (
                "split_drawn_only_by_a_condition_at_zero_rollout",
                _flag(_condition(0), _condition(100, EMAIL, variant="b"), variants=SPLIT_50_50),
                ("b",),
            ),
            (
                "disabled",
                _flag(_condition(100, EMAIL, variant="b"), _condition(100), variants=SPLIT_ALL_A, active=False),
                (),
            ),
            ("boolean_flag_with_a_leftover_override", _flag(_condition(100, variant="b")), ()),
            ("deleted", _flag(_condition(100), variants=SPLIT_ALL_A, deleted=True), ()),
        ]
    )
    def test_lists_the_variants_that_the_flag_serves(
        self, _name: str, after: FlagExposureConfig, served_variants: tuple[str, ...]
    ) -> None:
        change = classify_exposure_change(before=_flag(_condition(100), variants=SPLIT_ALL_A), after=after)

        assert change.served_variants == served_variants

    @parameterized.expand(
        [
            ("before", VERSION_2, _flag(_condition(50))),
            ("after", _flag(_condition(50)), VERSION_2),
        ]
    )
    def test_refuses_a_version_2_config(
        self, _name: str, before: FlagExposureConfig, after: FlagExposureConfig
    ) -> None:
        with self.assertRaises(ConfigFormatError):
            classify_exposure_change(before=before, after=after)
