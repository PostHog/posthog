from datetime import UTC, datetime, timedelta

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.health.bucketing_changes import BucketingChangeShape, bucketing_net_effect
from products.feature_flags.backend.facade.edits import BucketingChange, BucketingSetting

CHANGED_AT = datetime(2026, 9, 12, 13, 4, tzinfo=UTC)
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
