from datetime import UTC, datetime, timedelta

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.health.bucketing_changes import (
    BucketingChangeShape,
    bucketing_changes_from_activity,
    bucketing_net_effect,
    changes_that_apply,
)
from products.experiments.backend.health.context import BucketingChange, BucketingSetting

CHANGED_AT = datetime(2026, 9, 12, 13, 4, tzinfo=UTC)
FLAG_ID = 42
KEY = BucketingSetting.KEY
AGGREGATION = BucketingSetting.AGGREGATION
IDENTIFIER = BucketingSetting.BUCKETING_IDENTIFIER
CONTINUITY = BucketingSetting.EXPERIENCE_CONTINUITY


Value = str | int | bool | None


def _change(setting: BucketingSetting, before: Value, after: Value, *, minutes: int = 0) -> BucketingChange:
    return BucketingChange(
        changed_at=CHANGED_AT + timedelta(minutes=minutes), setting=setting, before=before, after=after
    )


class TestBucketingChanges(TestCase):
    @parameterized.expand(
        [
            ("key_renamed", {KEY: "old"}, {KEY: "new"}, [(KEY, "old", "new")]),
            ("key_tombstoned_on_delete", {KEY: "old"}, {KEY: f"old:deleted:{FLAG_ID}"}, []),
            ("key_restored_under_a_new_name", {KEY: f"old:deleted:{FLAG_ID}"}, {KEY: "old-2"}, [(KEY, "old", "old-2")]),
            (
                "identifier_to_device",
                {IDENTIFIER: "distinct_id"},
                {IDENTIFIER: "device_id"},
                [(IDENTIFIER, "distinct_id", "device_id")],
            ),
            ("identifier_default_written", {IDENTIFIER: None}, {IDENTIFIER: "distinct_id"}, []),
            ("continuity_on", {CONTINUITY: False}, {CONTINUITY: True}, [(CONTINUITY, False, True)]),
            ("continuity_default_written", {CONTINUITY: None}, {CONTINUITY: False}, []),
            ("aggregation_to_group", {AGGREGATION: None}, {AGGREGATION: 0}, [(AGGREGATION, None, 0)]),
            ("aggregation_boolean_is_unreadable", {AGGREGATION: None}, {AGGREGATION: False}, []),
            ("row_without_these_settings", {}, {}, []),
            (
                "one_save_changes_two",
                {KEY: "old", CONTINUITY: True},
                {KEY: "new", CONTINUITY: False},
                [(KEY, "old", "new"), (CONTINUITY, True, False)],
            ),
        ]
    )
    def test_bucketing_changes_from_activity(
        self,
        _name: str,
        before: dict[BucketingSetting, object],
        after: dict[BucketingSetting, object],
        expected: list[tuple[BucketingSetting, object, object]],
    ) -> None:
        changes = bucketing_changes_from_activity(
            changed_at=CHANGED_AT, feature_flag_id=FLAG_ID, before=before, after=after
        )

        self.assertEqual([(change.setting, change.before, change.after) for change in changes], expected)

    @parameterized.expand(
        [
            (
                "one_setting",
                [_change(CONTINUITY, False, True)],
                BucketingChangeShape.EXPERIENCE_CONTINUITY_CHANGED,
                [CONTINUITY],
                1,
            ),
            (
                "key_named_first_whatever_the_order",
                [_change(CONTINUITY, False, True), _change(KEY, "old", "new", minutes=5)],
                BucketingChangeShape.KEY_CHANGED,
                [KEY, CONTINUITY],
                2,
            ),
            (
                "set_back",
                [
                    _change(IDENTIFIER, "distinct_id", "device_id"),
                    _change(IDENTIFIER, "device_id", "distinct_id", minutes=6),
                ],
                BucketingChangeShape.REVERTED,
                [],
                2,
            ),
            (
                "one_set_back_one_kept",
                [
                    _change(IDENTIFIER, "distinct_id", "device_id"),
                    _change(CONTINUITY, True, False),
                    _change(IDENTIFIER, "device_id", "distinct_id", minutes=6),
                ],
                BucketingChangeShape.EXPERIENCE_CONTINUITY_CHANGED,
                [CONTINUITY],
                2,
            ),
        ]
    )
    def test_bucketing_net_effect(
        self,
        _name: str,
        changes: list[BucketingChange],
        expected_shape: BucketingChangeShape,
        expected_net_settings: list[BucketingSetting],
        expected_change_count: int,
    ) -> None:
        effect = bucketing_net_effect(changes)

        assert effect is not None
        self.assertEqual(effect.shape, expected_shape)
        self.assertEqual([change.setting for change in effect.net_changes], expected_net_settings)
        self.assertEqual(effect.change_count, expected_change_count)

    @parameterized.expand(
        [
            ("identifier_on_a_user_flag", [_change(IDENTIFIER, "distinct_id", "device_id")], None, None, [IDENTIFIER]),
            ("identifier_on_a_group_flag", [_change(IDENTIFIER, "distinct_id", "device_id")], 0, None, []),
            ("continuity_under_user_id", [_change(CONTINUITY, False, True)], None, None, [CONTINUITY]),
            ("continuity_under_device_id", [_change(CONTINUITY, True, False)], None, "device_id", []),
            ("continuity_on_a_group_flag", [_change(CONTINUITY, False, True)], 0, None, []),
            # The state right after each save decides, not the state today.
            (
                "identifier_before_a_switch_to_groups",
                [_change(IDENTIFIER, "distinct_id", "device_id"), _change(AGGREGATION, None, 0, minutes=5)],
                0,
                "device_id",
                [IDENTIFIER, AGGREGATION],
            ),
            (
                "continuity_in_the_save_that_switches_to_device_id",
                [_change(IDENTIFIER, "distinct_id", "device_id"), _change(CONTINUITY, True, False)],
                None,
                "device_id",
                [IDENTIFIER],
            ),
            ("key_on_a_group_flag", [_change(KEY, "old", "new")], 0, None, [KEY]),
        ]
    )
    def test_changes_that_apply(
        self,
        _name: str,
        changes: list[BucketingChange],
        aggregation: int | None,
        bucketing_identifier: str | None,
        expected: list[BucketingSetting],
    ) -> None:
        kept = changes_that_apply(
            changes, feature_flag_id=FLAG_ID, aggregation=aggregation, bucketing_identifier=bucketing_identifier
        )

        self.assertEqual([change.setting for change in kept], expected)
