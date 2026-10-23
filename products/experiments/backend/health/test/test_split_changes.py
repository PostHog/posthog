from datetime import UTC, datetime, timedelta
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.health.split_changes import (
    SplitChangeShape,
    net_effect,
    split_change_from_activity,
    split_shape,
)
from products.feature_flags.backend.facade.edits import SplitChange

CHANGED_AT = datetime(2026, 9, 12, 13, 4, tzinfo=UTC)


def _split(*variants: tuple[str | None, Any]) -> list[dict[str, Any]]:
    return [{"key": key, "rollout_percentage": share} for key, share in variants]


def _row(before: Any, after: Any, *, job_type: str | None = None) -> dict[str, Any]:
    return {"job_type": job_type, "before_variants": before, "after_variants": after}


EVEN = _split(("control", 50), ("test", 50))
THREE_WAY = _split(("control", 34), ("test", 33), ("blue", 33))
BLUE_AT_ZERO = _split(("control", 50), ("test", 50), ("blue", 0))


class TestSplitChanges(TestCase):
    @parameterized.expand(
        [
            ("rebalanced", _row(EVEN, _split(("control", 80), ("test", 20))), SplitChangeShape.REBALANCED),
            ("reordered", _row(EVEN, _split(("test", 50), ("control", 50))), SplitChangeShape.REORDERED),
            ("variant_added", _row(EVEN, THREE_WAY), SplitChangeShape.VARIANT_ADDED),
            ("variant_removed", _row(THREE_WAY, EVEN), SplitChangeShape.VARIANT_REMOVED),
            ("renamed", _row(EVEN, _split(("control", 50), ("treatment", 50))), SplitChangeShape.VARIANT_REMOVED),
            (
                "variant_zeroed",
                _row(THREE_WAY, _split(("control", 50), ("test", 50), ("blue", 0))),
                SplitChangeShape.VARIANT_ZEROED,
            ),
            (
                "rolled_out_wins_over_zeroed",
                _row(EVEN, _split(("control", 0), ("test", 100))),
                SplitChangeShape.VARIANT_ROLLED_OUT,
            ),
            (
                "variant_at_100_switched",
                _row(_split(("control", 100), ("test", 0)), _split(("control", 0), ("test", 100))),
                SplitChangeShape.VARIANT_ROLLED_OUT,
            ),
            ("integer_against_float", _row(EVEN, _split(("control", 50.0), ("test", 50.0))), None),
            (
                "display_name_only",
                _row(
                    EVEN,
                    [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "New checkout", "rollout_percentage": 50},
                    ],
                ),
                None,
            ),
            (
                "exposure_freeze",
                _row(EVEN, _split(("control", 80), ("test", 20)), job_type="experiment_exposure_frozen"),
                None,
            ),
            ("variant_added_at_zero", _row(EVEN, BLUE_AT_ZERO), None),
            ("variant_at_zero_removed", _row(BLUE_AT_ZERO, EVEN), None),
            (
                "variant_at_zero_renamed",
                _row(BLUE_AT_ZERO, _split(("control", 50), ("test", 50), ("green", 0))),
                None,
            ),
            (
                "variant_at_zero_moved",
                _row(_split(("control", 50), ("blue", 0), ("test", 50)), BLUE_AT_ZERO),
                None,
            ),
            ("variant_raised_from_zero", _row(BLUE_AT_ZERO, THREE_WAY), SplitChangeShape.REBALANCED),
            (
                "served_variant_swapped_for_one_at_zero",
                _row(_split(("control", 50), ("test", 0), ("blue", 50)), BLUE_AT_ZERO),
                SplitChangeShape.VARIANT_ZEROED,
            ),
            (
                "variant_added_at_zero_with_a_rebalance",
                _row(EVEN, _split(("control", 80), ("test", 20), ("blue", 0))),
                SplitChangeShape.REBALANCED,
            ),
            (
                "variant_without_key_zeroed",
                _row(
                    _split(("control", 34), ("test", 33), (None, 33)),
                    _split(("control", 50), ("test", 50), (None, 0)),
                ),
                SplitChangeShape.REBALANCED,
            ),
            ("no_variants_on_either_side", _row(None, None), None),
        ]
    )
    def test_split_change_from_activity(
        self, _name: str, row: dict[str, Any], expected_shape: SplitChangeShape | None
    ) -> None:
        change = split_change_from_activity(changed_at=CHANGED_AT, **row)

        if expected_shape is None:
            self.assertIsNone(change)
            return
        assert change is not None
        self.assertEqual(split_shape(change.before, change.after), expected_shape)

    @parameterized.expand(
        [
            (
                "net_effect_of_a_sequence",
                [EVEN, _split(("control", 70), ("test", 30)), THREE_WAY],
                SplitChangeShape.VARIANT_ADDED,
            ),
            ("set_back", [EVEN, _split(("control", 0), ("test", 100)), EVEN], SplitChangeShape.REVERTED),
            (
                "set_back_with_a_variant_left_at_zero",
                [EVEN, _split(("control", 80), ("test", 20)), BLUE_AT_ZERO],
                SplitChangeShape.REVERTED,
            ),
        ]
    )
    def test_net_effect(
        self, _name: str, sequence: list[list[dict[str, Any]]], expected_shape: SplitChangeShape
    ) -> None:
        changes = tuple(
            _split_change(before, after, CHANGED_AT + timedelta(hours=index))
            for index, (before, after) in enumerate(zip(sequence, sequence[1:]))
        )

        effect = net_effect(changes)

        assert effect is not None
        self.assertEqual((effect.shape, effect.change_count), (expected_shape, len(sequence) - 1))
        self.assertEqual((effect.from_split, effect.to_split), (changes[0].before, changes[-1].after))


def _split_change(before: list[dict[str, Any]], after: list[dict[str, Any]], changed_at: datetime) -> SplitChange:
    change = split_change_from_activity(changed_at=changed_at, **_row(before, after))
    assert change is not None
    return change
