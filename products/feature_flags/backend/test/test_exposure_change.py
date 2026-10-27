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

ENABLED = ExposureChangeKind.ENABLED
DISABLED = ExposureChangeKind.DISABLED
ROLLOUT_INCREASED = ExposureChangeKind.ROLLOUT_INCREASED
ROLLOUT_DECREASED = ExposureChangeKind.ROLLOUT_DECREASED
CONDITION_ADDED = ExposureChangeKind.CONDITION_ADDED
CONDITION_REMOVED = ExposureChangeKind.CONDITION_REMOVED
PROPERTIES_CHANGED = ExposureChangeKind.PROPERTIES_CHANGED
VARIANT_CHANGED = ExposureChangeKind.VARIANT_CHANGED
RAISES = ExposureDirection.RAISES
LOWERS = ExposureDirection.LOWERS
KEEPS = ExposureDirection.KEEPS


def _condition(
    rollout: float, properties: list[dict[str, Any]] | None = None, variant: str | None = None
) -> dict[str, Any]:
    return {"properties": properties or [], "rollout_percentage": rollout, "variant": variant}


def _flag(
    *conditions: dict[str, Any],
    active: bool = True,
    variants: list[dict[str, Any]] | None = None,
    aggregation: int | None = None,
    early_exit: bool = False,
) -> FlagExposureConfig:
    filters: dict[str, Any] = {
        "groups": list(conditions),
        "aggregation_group_type_index": aggregation,
        "early_exit": early_exit,
    }
    if variants is not None:
        filters["multivariate"] = {"variants": variants}
    return FlagExposureConfig(active=active, filters=filters)


class TestClassifyExposureChange(TestCase):
    @parameterized.expand(
        [
            ("no_change", _flag(_condition(50)), _flag(_condition(50)), set(), False, (), KEEPS),
            (
                "edit_of_a_disabled_flag",
                _flag(_condition(10), active=False),
                _flag(_condition(100), active=False),
                set(),
                False,
                (),
                KEEPS,
            ),
            (
                "enabled",
                _flag(_condition(50), active=False),
                _flag(_condition(50)),
                {ENABLED},
                True,
                (),
                RAISES,
            ),
            (
                "enabled_at_zero_rollout",
                _flag(_condition(0), active=False),
                _flag(_condition(0)),
                set(),
                False,
                (),
                KEEPS,
            ),
            (
                "disabled",
                _flag(_condition(50)),
                _flag(_condition(50), active=False),
                {DISABLED},
                False,
                (),
                LOWERS,
            ),
            ("rollout_increased", _flag(_condition(10)), _flag(_condition(50)), {ROLLOUT_INCREASED}, True, (), RAISES),
            ("rollout_decreased", _flag(_condition(50)), _flag(_condition(10)), {ROLLOUT_DECREASED}, False, (), LOWERS),
            (
                "condition_added",
                _flag(_condition(100, EMAIL)),
                _flag(_condition(100, EMAIL), _condition(20)),
                {CONDITION_ADDED},
                True,
                (),
                RAISES,
            ),
            (
                "condition_added_at_zero_rollout",
                _flag(_condition(100, EMAIL)),
                _flag(_condition(100, EMAIL), _condition(0)),
                set(),
                False,
                (),
                KEEPS,
            ),
            (
                "condition_removed",
                _flag(_condition(100, EMAIL), _condition(20)),
                _flag(_condition(100, EMAIL)),
                {CONDITION_REMOVED},
                False,
                (),
                LOWERS,
            ),
            (
                "properties_changed",
                _flag(_condition(100, EMAIL)),
                _flag(_condition(100, OTHER_EMAIL)),
                {PROPERTIES_CHANGED},
                True,
                (),
                RAISES,
            ),
            (
                "flag_aggregation_changed",
                _flag(_condition(100)),
                _flag(_condition(100), aggregation=0),
                {PROPERTIES_CHANGED},
                True,
                (),
                RAISES,
            ),
            (
                "flag_aggregation_changed_on_a_flag_that_serves_nobody",
                _flag(_condition(0)),
                _flag(_condition(0), aggregation=0),
                set(),
                False,
                (),
                KEEPS,
            ),
            (
                "variant_with_a_smaller_share_gets_new_people",
                _flag(_condition(100), variants=SPLIT_50_50),
                _flag(
                    _condition(100),
                    variants=[{"key": "b", "rollout_percentage": 40}, {"key": "a", "rollout_percentage": 60}],
                ),
                {VARIANT_CHANGED},
                False,
                ("b", "a"),
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
                False,
                (),
                KEEPS,
            ),
            (
                "multivariate_flag_made_boolean",
                _flag(_condition(100), variants=SPLIT_50_50),
                _flag(_condition(100)),
                {VARIANT_CHANGED},
                False,
                (),
                RAISES,
            ),
            (
                "removed_override_condition_falls_through_to_another_variant",
                _flag(_condition(100, EMAIL, variant="b"), _condition(100), variants=SPLIT_50_50),
                _flag(_condition(100), variants=SPLIT_50_50),
                {CONDITION_REMOVED, VARIANT_CHANGED},
                False,
                ("a",),
                RAISES,
            ),
            (
                "lowered_override_condition_falls_through_to_another_variant",
                _flag(_condition(100, EMAIL, variant="b"), _condition(100), variants=SPLIT_50_50),
                _flag(_condition(10, EMAIL, variant="b"), _condition(100), variants=SPLIT_50_50),
                {ROLLOUT_DECREASED, VARIANT_CHANGED},
                False,
                ("a",),
                RAISES,
            ),
            (
                "lowered_override_condition_with_early_exit",
                _flag(_condition(100, EMAIL, variant="b"), _condition(100), variants=SPLIT_50_50, early_exit=True),
                _flag(_condition(10, EMAIL, variant="b"), _condition(100), variants=SPLIT_50_50, early_exit=True),
                {ROLLOUT_DECREASED},
                False,
                (),
                LOWERS,
            ),
            (
                "leading_override_condition_added",
                _flag(_condition(100), variants=SPLIT_50_50),
                _flag(_condition(100, EMAIL, variant="b"), _condition(100), variants=SPLIT_50_50),
                {CONDITION_ADDED},
                True,
                ("b",),
                RAISES,
            ),
            (
                "split_changed",
                _flag(_condition(100), variants=SPLIT_50_50),
                _flag(
                    _condition(100),
                    variants=[{"key": "a", "rollout_percentage": 30}, {"key": "b", "rollout_percentage": 70}],
                ),
                {VARIANT_CHANGED},
                False,
                ("b",),
                RAISES,
            ),
            (
                "split_reordered",
                _flag(_condition(100), variants=SPLIT_50_50),
                _flag(_condition(100), variants=list(reversed(SPLIT_50_50))),
                {VARIANT_CHANGED},
                False,
                ("b", "a"),
                RAISES,
            ),
            (
                "boolean_flag_made_multivariate",
                _flag(_condition(100)),
                _flag(_condition(100), variants=SPLIT_50_50),
                {VARIANT_CHANGED},
                False,
                ("a", "b"),
                RAISES,
            ),
            (
                "override_added",
                _flag(_condition(100), variants=SPLIT_50_50),
                _flag(_condition(100, variant="b"), variants=SPLIT_50_50),
                {VARIANT_CHANGED},
                False,
                ("b",),
                RAISES,
            ),
            (
                "override_removed",
                _flag(_condition(100, variant="b"), variants=SPLIT_50_50),
                _flag(_condition(100), variants=SPLIT_50_50),
                {VARIANT_CHANGED},
                False,
                ("a",),
                RAISES,
            ),
            (
                "override_changed_on_a_condition_turned_off",
                _flag(_condition(50, variant="b"), variants=SPLIT_50_50),
                _flag(_condition(0, variant="a"), variants=SPLIT_50_50),
                {ROLLOUT_DECREASED},
                False,
                (),
                LOWERS,
            ),
            (
                "conditions_with_different_overrides_reordered",
                _flag(_condition(100, EMAIL, variant="a"), _condition(100, variant="b"), variants=SPLIT_50_50),
                _flag(_condition(100, variant="b"), _condition(100, EMAIL, variant="a"), variants=SPLIT_50_50),
                {VARIANT_CHANGED},
                False,
                ("a", "b"),
                RAISES,
            ),
            (
                "rollout_increased_and_condition_removed",
                _flag(_condition(10, EMAIL), _condition(20)),
                _flag(_condition(50, EMAIL)),
                {ROLLOUT_INCREASED, CONDITION_REMOVED},
                True,
                (),
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
        reaches_new_people: bool,
        grown_variants: tuple[str, ...],
        direction: ExposureDirection,
    ) -> None:
        change = classify_exposure_change(before=before, after=after)

        assert change.kinds == kinds
        assert change.reaches_new_people == reaches_new_people
        assert change.grown_variants == grown_variants
        assert change.direction == direction

    def test_returns_the_group_type_after_the_edit(self) -> None:
        change = classify_exposure_change(
            before=_flag(_condition(50), aggregation=0), after=_flag(_condition(50), aggregation=1)
        )

        assert change.aggregation == 1

    def test_refuses_a_version_2_config(self) -> None:
        with self.assertRaises(ConfigFormatError):
            classify_exposure_change(
                before=_flag(_condition(50)), after=FlagExposureConfig(active=True, filters={"version": 2})
            )
