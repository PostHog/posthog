from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.feature_flags.backend.launch_check import (
    FlagLaunchSide,
    LaunchCheck,
    LaunchReason,
    ReleasePath,
    check_launch,
)

EMAIL = [{"key": "email", "type": "person", "operator": "icontains", "value": "@example.com"}]
SPLIT_50_50 = [{"key": "a", "rollout_percentage": 50}, {"key": "b", "rollout_percentage": 50}]
SPLIT_ALL_A = [{"key": "a", "rollout_percentage": 100}, {"key": "b", "rollout_percentage": 0}]
SPLIT_60_40 = [{"key": "a", "rollout_percentage": 60}, {"key": "b", "rollout_percentage": 40}]


def _condition(
    rollout: float | None, properties: list[dict[str, Any]] | None = None, aggregation: int | None = None
) -> dict[str, Any]:
    condition: dict[str, Any] = {"properties": properties or [], "rollout_percentage": rollout}
    if aggregation is not None:
        condition["aggregation_group_type_index"] = aggregation
    return condition


def _flag(
    *conditions: dict[str, Any],
    active: bool = True,
    deleted: bool = False,
    archived: bool = False,
    variants: list[dict[str, Any]] | None = None,
    aggregation: int | None = None,
    early_exit: bool = False,
    holdout: bool = False,
    enrollment: bool = False,
    runtime: str | None = "all",
    extra: dict[str, Any] | None = None,
) -> FlagLaunchSide:
    filters: dict[str, Any] = {"groups": list(conditions), **(extra or {})}
    if variants is not None:
        filters["multivariate"] = {"variants": variants}
    if aggregation is not None:
        filters["aggregation_group_type_index"] = aggregation
    if early_exit:
        filters["early_exit"] = True
    if holdout:
        filters["holdout"] = {"id": 1, "exclusion_percentage": 10}
    if enrollment:
        filters["feature_enrollment"] = True
    return FlagLaunchSide(
        active=active, deleted=deleted, archived=archived, filters=filters, evaluation_runtime=runtime
    )


def _qualified(release_path: ReleasePath) -> LaunchCheck:
    return LaunchCheck(qualified=True, reason=None, release_path=release_path)


def _not_qualified(reason: LaunchReason, release_path: ReleasePath) -> LaunchCheck:
    return LaunchCheck(qualified=False, reason=reason, release_path=release_path)


class TestCheckLaunch(TestCase):
    @parameterized.expand(
        [
            (
                "partial_rollout_to_full",
                _flag(_condition(50)),
                _flag(_condition(100)),
                _qualified(ReleasePath.CONDITIONS),
            ),
            ("zero_rollout_to_full", _flag(_condition(0)), _flag(_condition(None)), _qualified(ReleasePath.CONDITIONS)),
            (
                "property_condition_with_everyone_on_top",
                _flag(_condition(100, EMAIL)),
                _flag(_condition(100), _condition(100, EMAIL)),
                _qualified(ReleasePath.CONDITIONS),
            ),
            (
                "disabled_partial_flag_enabled_at_full",
                _flag(_condition(30), active=False),
                _flag(_condition(100)),
                _qualified(ReleasePath.CONDITIONS),
            ),
            (
                "enrollment_removed_for_everyone",
                _flag(_condition(0), enrollment=True),
                _flag(_condition(100)),
                _qualified(ReleasePath.ENROLLMENT_REMOVED),
            ),
            (
                "re_enabled_full_flag",
                _flag(_condition(100), active=False),
                _flag(_condition(100)),
                _not_qualified(LaunchReason.NOT_STAGED_BEFORE, ReleasePath.ENABLED),
            ),
            (
                "restored_full_flag",
                _flag(_condition(100), deleted=True),
                _flag(_condition(100)),
                _not_qualified(LaunchReason.NOT_STAGED_BEFORE, ReleasePath.ENABLED),
            ),
            (
                "holdout_removed_from_full_flag",
                _flag(_condition(100), holdout=True),
                _flag(_condition(100)),
                _not_qualified(LaunchReason.NOT_STAGED_BEFORE, ReleasePath.CONDITIONS),
            ),
            (
                "partial_condition_ahead_under_early_exit",
                _flag(_condition(50), early_exit=True),
                _flag(_condition(50, EMAIL), _condition(100), early_exit=True),
                _not_qualified(LaunchReason.EARLY_EXIT, ReleasePath.CONDITIONS),
            ),
            (
                "holdout_kept",
                _flag(_condition(50), holdout=True),
                _flag(_condition(100), holdout=True),
                _not_qualified(LaunchReason.HOLDOUT, ReleasePath.CONDITIONS),
            ),
            (
                "server_runtime",
                _flag(_condition(50), runtime="server"),
                _flag(_condition(100), runtime="server"),
                _not_qualified(LaunchReason.RUNTIME_RESTRICTED, ReleasePath.CONDITIONS),
            ),
            (
                "group_flag",
                _flag(_condition(50), aggregation=0),
                _flag(_condition(100), aggregation=0),
                _not_qualified(LaunchReason.GROUP, ReleasePath.CONDITIONS),
            ),
            (
                "group_condition_on_person_flag",
                _flag(_condition(50, aggregation=0)),
                _flag(_condition(100, aggregation=0)),
                _not_qualified(LaunchReason.GROUP, ReleasePath.CONDITIONS),
            ),
            (
                "enrollment_kept",
                _flag(_condition(50), enrollment=True),
                _flag(_condition(100), enrollment=True),
                _not_qualified(LaunchReason.ENROLLMENT, ReleasePath.CONDITIONS),
            ),
            (
                "person_condition_opened_beside_open_group_condition",
                _flag(_condition(100, aggregation=0), _condition(50)),
                _flag(_condition(100, aggregation=0), _condition(100)),
                _qualified(ReleasePath.CONDITIONS),
            ),
            (
                "re_enabled_flag_with_shadowed_partial_condition",
                _flag(_condition(100), _condition(50), active=False),
                _flag(_condition(100), _condition(50)),
                _not_qualified(LaunchReason.NOT_STAGED_BEFORE, ReleasePath.ENABLED),
            ),
            (
                "partial_group_condition_ahead_under_early_exit",
                _flag(_condition(50), early_exit=True),
                _flag(_condition(0, aggregation=0), _condition(100), early_exit=True),
                _not_qualified(LaunchReason.EARLY_EXIT, ReleasePath.CONDITIONS),
            ),
            (
                "re_enabled_flag_with_partial_group_condition_shadowed",
                _flag(_condition(100, aggregation=0), _condition(50, aggregation=0), _condition(100), active=False),
                _flag(_condition(100, aggregation=0), _condition(50, aggregation=0), _condition(100)),
                _not_qualified(LaunchReason.NOT_STAGED_BEFORE, ReleasePath.ENABLED),
            ),
            (
                "shadowed_zero_group_condition_ahead_under_early_exit",
                _flag(_condition(50), early_exit=True),
                _flag(_condition(100, aggregation=0), _condition(0, aggregation=0), _condition(100), early_exit=True),
                _qualified(ReleasePath.CONDITIONS),
            ),
            (
                "early_exit_turned_off_on_group_flag",
                _flag(_condition(50), _condition(100), aggregation=0, early_exit=True),
                _flag(_condition(50), _condition(100), aggregation=0),
                _not_qualified(LaunchReason.GROUP, ReleasePath.CONDITIONS),
            ),
            (
                "second_group_type_opened_under_early_exit",
                _flag(
                    _condition(50, aggregation=0),
                    _condition(100, aggregation=0),
                    _condition(50, aggregation=1),
                    early_exit=True,
                ),
                _flag(
                    _condition(50, aggregation=0),
                    _condition(100, aggregation=0),
                    _condition(100, aggregation=1),
                    early_exit=True,
                ),
                _not_qualified(LaunchReason.GROUP, ReleasePath.CONDITIONS),
            ),
            (
                "re_enabled_flag_with_partial_condition_above_fallback",
                _flag(_condition(100, aggregation=0), _condition(50), _condition(100), active=False),
                _flag(_condition(100, aggregation=0), _condition(50), _condition(100)),
                _not_qualified(LaunchReason.NOT_STAGED_BEFORE, ReleasePath.ENABLED),
            ),
            (
                "variant_rolled_out_from_staged_flag",
                _flag(_condition(50), variants=SPLIT_50_50),
                _flag(_condition(100), variants=SPLIT_ALL_A),
                _not_qualified(LaunchReason.MULTIVARIATE, ReleasePath.VARIANT_ROLLOUT),
            ),
        ]
    )
    def test_candidate_save(self, _name: str, before: FlagLaunchSide, after: FlagLaunchSide, expected: LaunchCheck):
        self.assertEqual(check_launch(before, after), expected)

    @parameterized.expand(
        [
            ("re_save_of_full_flag", _flag(_condition(100)), _flag(_condition(100))),
            (
                "variant_ship_on_flag_that_reached_everyone",
                _flag(_condition(100), variants=SPLIT_50_50),
                _flag(_condition(100), variants=SPLIT_ALL_A),
            ),
            ("rollout_raised_short_of_everyone", _flag(_condition(50)), _flag(_condition(60))),
            ("property_condition_at_full", _flag(_condition(50, EMAIL)), _flag(_condition(100, EMAIL))),
            ("archived_after", _flag(_condition(50)), _flag(_condition(100), archived=True)),
            ("disabled_after", _flag(_condition(50)), _flag(_condition(100), active=False)),
            (
                "re_save_of_full_group_flag",
                _flag(_condition(100), aggregation=0),
                _flag(_condition(100), aggregation=0),
            ),
            (
                "group_condition_opened_on_flag_that_reached_everyone",
                _flag(_condition(100), _condition(50, aggregation=0)),
                _flag(_condition(100), _condition(100, aggregation=0)),
            ),
            (
                "re_save_of_full_server_flag",
                _flag(_condition(100), runtime="server"),
                _flag(_condition(100), runtime="server"),
            ),
            (
                "re_save_of_full_holdout_flag",
                _flag(_condition(50), _condition(100), holdout=True),
                _flag(_condition(100), holdout=True),
            ),
            (
                "super_groups_dropped_from_full_flag",
                _flag(_condition(100), extra={"super_groups": [_condition(100, EMAIL)]}),
                _flag(_condition(100)),
            ),
            (
                "holdout_groups_dropped_from_full_flag",
                _flag(_condition(100), extra={"holdout_groups": [_condition(10)]}),
                _flag(_condition(100)),
            ),
            (
                "full_group_flag_moved_to_server_runtime",
                _flag(_condition(100), aggregation=0),
                _flag(_condition(100), aggregation=0, runtime="server"),
            ),
            (
                "person_fallback_removed_under_early_exit",
                _flag(_condition(100, aggregation=0), _condition(50, aggregation=1), _condition(100), early_exit=True),
                _flag(_condition(100, aggregation=0), _condition(50, aggregation=1), early_exit=True),
            ),
            (
                "group_condition_opened_behind_ending_person_condition",
                _flag(_condition(100, aggregation=0), _condition(25), _condition(50, aggregation=1), early_exit=True),
                _flag(_condition(100, aggregation=0), _condition(25), _condition(100, aggregation=1), early_exit=True),
            ),
            (
                "variant_split_change_on_full_flag",
                _flag(_condition(100), variants=SPLIT_50_50),
                _flag(_condition(100), variants=SPLIT_60_40),
            ),
        ]
    )
    def test_save_that_does_not_newly_reach_everyone(self, _name: str, before: FlagLaunchSide, after: FlagLaunchSide):
        self.assertIsNone(check_launch(before, after))

    def test_config_version_2_is_not_read(self):
        version_2 = FlagLaunchSide(
            active=True, deleted=False, archived=False, filters={"version": 2}, evaluation_runtime="all"
        )
        self.assertIsNone(check_launch(_flag(_condition(50)), version_2))
