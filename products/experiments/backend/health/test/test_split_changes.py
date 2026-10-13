from datetime import UTC, datetime, timedelta
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.health.context import SplitChange, SplitHistory
from products.experiments.backend.health.split_changes import (
    SplitChangeShape,
    net_effect,
    split_change_from_activity,
    split_shape,
)

CHANGED_AT = datetime(2026, 9, 12, 13, 4, tzinfo=UTC)


def _filters(*variants: tuple[str | None, Any], **extra: Any) -> dict[str, Any]:
    return {
        "groups": [{"properties": [], "rollout_percentage": 100}],
        "multivariate": {"variants": [{"key": key, "rollout_percentage": share} for key, share in variants]},
        **extra,
    }


def _detail(before: dict[str, Any], after: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "changes": [
            {"type": "FeatureFlag", "action": "changed", "field": "name", "before": "old", "after": "new"},
            {"type": "FeatureFlag", "action": "changed", "field": "filters", "before": before, "after": after},
        ],
        **extra,
    }


EVEN = _filters(("control", 50), ("test", 50))
THREE_WAY = _filters(("control", 34), ("test", 33), ("blue", 33))
BLUE_AT_ZERO = _filters(("control", 50), ("test", 50), ("blue", 0))


class TestSplitChanges(TestCase):
    @parameterized.expand(
        [
            ("rebalanced", _detail(EVEN, _filters(("control", 80), ("test", 20))), SplitChangeShape.REBALANCED),
            ("reordered", _detail(EVEN, _filters(("test", 50), ("control", 50))), SplitChangeShape.REORDERED),
            ("variant_added", _detail(EVEN, THREE_WAY), SplitChangeShape.VARIANT_ADDED),
            ("variant_removed", _detail(THREE_WAY, EVEN), SplitChangeShape.VARIANT_REMOVED),
            ("renamed", _detail(EVEN, _filters(("control", 50), ("treatment", 50))), SplitChangeShape.VARIANT_REMOVED),
            (
                "variant_zeroed",
                _detail(THREE_WAY, _filters(("control", 50), ("test", 50), ("blue", 0))),
                SplitChangeShape.VARIANT_ZEROED,
            ),
            (
                "rolled_out_wins_over_zeroed",
                _detail(EVEN, _filters(("control", 0), ("test", 100))),
                SplitChangeShape.VARIANT_ROLLED_OUT,
            ),
            (
                "variant_at_100_switched",
                _detail(_filters(("control", 100), ("test", 0)), _filters(("control", 0), ("test", 100))),
                SplitChangeShape.VARIANT_ROLLED_OUT,
            ),
            (
                "rolled_out_with_holdout",
                _detail(
                    _filters(("control", 50), ("test", 50), holdout={"id": 1, "exclusion_percentage": 10}),
                    _filters(("control", 0), ("test", 100), holdout={"id": 1, "exclusion_percentage": 10}),
                ),
                SplitChangeShape.VARIANT_ROLLED_OUT,
            ),
            ("integer_against_float", _detail(EVEN, _filters(("control", 50.0), ("test", 50.0))), None),
            (
                "display_name_only",
                _detail(
                    EVEN,
                    {
                        **EVEN,
                        "multivariate": {
                            "variants": [
                                {"key": "control", "name": "Control", "rollout_percentage": 50},
                                {"key": "test", "name": "New checkout", "rollout_percentage": 50},
                            ]
                        },
                    },
                ),
                None,
            ),
            ("payload_only", _detail(EVEN, {**EVEN, "payloads": {"test": '{"color": "blue"}'}}), None),
            (
                "holdout_only",
                _detail(EVEN, {**EVEN, "holdout": {"id": 1, "exclusion_percentage": 10}}),
                None,
            ),
            (
                "exposure_freeze",
                _detail(
                    EVEN,
                    _filters(("control", 80), ("test", 20)),
                    trigger={"job_type": "experiment_exposure_frozen", "job_id": "1", "payload": {}},
                ),
                None,
            ),
            ("variant_added_at_zero", _detail(EVEN, BLUE_AT_ZERO), None),
            ("variant_at_zero_removed", _detail(BLUE_AT_ZERO, EVEN), None),
            (
                "variant_at_zero_renamed",
                _detail(BLUE_AT_ZERO, _filters(("control", 50), ("test", 50), ("green", 0))),
                None,
            ),
            (
                "variant_at_zero_moved",
                _detail(_filters(("control", 50), ("blue", 0), ("test", 50)), BLUE_AT_ZERO),
                None,
            ),
            ("variant_raised_from_zero", _detail(BLUE_AT_ZERO, THREE_WAY), SplitChangeShape.REBALANCED),
            (
                "served_variant_swapped_for_one_at_zero",
                _detail(_filters(("control", 50), ("test", 0), ("blue", 50)), BLUE_AT_ZERO),
                SplitChangeShape.VARIANT_ZEROED,
            ),
            (
                "variant_added_at_zero_with_a_rebalance",
                _detail(EVEN, _filters(("control", 80), ("test", 20), ("blue", 0))),
                SplitChangeShape.REBALANCED,
            ),
            (
                "variant_without_key_zeroed",
                _detail(
                    _filters(("control", 34), ("test", 33), (None, 33)),
                    _filters(("control", 50), ("test", 50), (None, 0)),
                ),
                SplitChangeShape.REBALANCED,
            ),
            ("no_filters_change", {"changes": [{"field": "name", "before": "a", "after": "b"}]}, None),
            ("created_row", {"changes": None}, None),
        ]
    )
    def test_split_change_from_activity(
        self, _name: str, detail: dict[str, Any], expected_shape: SplitChangeShape | None
    ) -> None:
        change = split_change_from_activity(detail, CHANGED_AT)

        if expected_shape is None:
            self.assertIsNone(change)
            return
        assert change is not None
        self.assertEqual(split_shape(change.before, change.after), expected_shape)

    @parameterized.expand(
        [
            (
                "net_effect_of_a_sequence",
                [EVEN, _filters(("control", 70), ("test", 30)), THREE_WAY],
                SplitChangeShape.VARIANT_ADDED,
            ),
            ("set_back", [EVEN, _filters(("control", 0), ("test", 100)), EVEN], SplitChangeShape.REVERTED),
            (
                "set_back_with_a_variant_left_at_zero",
                [EVEN, _filters(("control", 80), ("test", 20)), BLUE_AT_ZERO],
                SplitChangeShape.REVERTED,
            ),
        ]
    )
    def test_net_effect(self, _name: str, sequence: list[dict[str, Any]], expected_shape: SplitChangeShape) -> None:
        changes = tuple(
            _split_change(before, after, CHANGED_AT + timedelta(hours=index))
            for index, (before, after) in enumerate(zip(sequence, sequence[1:]))
        )
        history = SplitHistory(
            launched_at=CHANGED_AT - timedelta(days=1),
            team_timezone="UTC",
            counted_changes=changes,
            exposed_before_first=True,
            exposed_between=None,
        )

        effect = net_effect(history)

        assert effect is not None
        self.assertEqual((effect.shape, effect.change_count), (expected_shape, len(sequence) - 1))
        self.assertEqual((effect.from_split, effect.to_split), (changes[0].before, changes[-1].after))


def _split_change(before: dict[str, Any], after: dict[str, Any], changed_at: datetime) -> SplitChange:
    change = split_change_from_activity(_detail(before, after), changed_at)
    assert change is not None
    return change
