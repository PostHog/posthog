from datetime import UTC, datetime, timedelta
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.health.condition_changes import (
    ConditionsChangeShape,
    conditions_change_from_activity,
    conditions_net_effect,
)
from products.experiments.backend.health.context import ConditionsChange

CHANGED_AT = datetime(2026, 9, 12, 13, 4, tzinfo=UTC)
PRO = {"key": "plan", "value": ["pro"], "operator": "exact", "type": "person"}
EU = {"key": "$geoip_continent_code", "value": ["EU"], "operator": "exact", "type": "person"}


def _condition(
    *properties: dict[str, Any], rollout: int = 100, variant: str | None = None, **extra: Any
) -> dict[str, Any]:
    return {"properties": list(properties), "rollout_percentage": rollout, "variant": variant, **extra}


def _change(before: list[dict[str, Any]], after: list[dict[str, Any]], *, minutes: int = 0) -> ConditionsChange:
    change = conditions_change_from_activity(
        changed_at=CHANGED_AT + timedelta(minutes=minutes), job_type=None, before_groups=before, after_groups=after
    )
    assert change is not None
    return change


class TestConditionChanges(TestCase):
    @parameterized.expand(
        [
            ("criteria_changed", [_condition(PRO)], [_condition(EU)], None, ConditionsChangeShape.CONDITIONS_CHANGED),
            (
                "condition_added",
                [_condition(PRO)],
                [_condition(PRO), _condition()],
                None,
                ConditionsChangeShape.CONDITIONS_CHANGED,
            ),
            (
                "condition_removed",
                [_condition(PRO), _condition()],
                [_condition()],
                None,
                ConditionsChangeShape.CONDITIONS_CHANGED,
            ),
            (
                "override_added",
                [_condition(PRO)],
                [_condition(PRO, variant="test")],
                None,
                ConditionsChangeShape.VARIANT_OVERRIDE_CHANGED,
            ),
            (
                "pinned_conditions_reordered",
                [_condition(PRO, variant="test"), _condition(EU, variant="control")],
                [_condition(EU, variant="control"), _condition(PRO, variant="test")],
                None,
                ConditionsChangeShape.VARIANT_OVERRIDE_CHANGED,
            ),
            ("rollout_only", [_condition(PRO, rollout=100)], [_condition(PRO, rollout=20)], None, None),
            ("description_only", [_condition(PRO)], [_condition(PRO, description="Pro users")], None, None),
            ("filters_reordered", [_condition(PRO, EU)], [_condition(EU, PRO)], None, None),
            (
                "unpinned_conditions_reordered",
                [_condition(PRO), _condition(EU)],
                [_condition(EU), _condition(PRO)],
                None,
                None,
            ),
            ("exposure_frozen", [_condition(PRO)], [_condition(PRO, EU)], "experiment_exposure_frozen", None),
            ("no_conditions_in_the_row", None, None, None, None),
        ]
    )
    def test_conditions_change_from_activity(
        self,
        _name: str,
        before: list[dict[str, Any]] | None,
        after: list[dict[str, Any]] | None,
        job_type: str | None,
        expected: ConditionsChangeShape | None,
    ) -> None:
        change = conditions_change_from_activity(
            changed_at=CHANGED_AT, job_type=job_type, before_groups=before, after_groups=after
        )
        effect = conditions_net_effect([change] if change else [])

        self.assertEqual(effect.shape if effect else None, expected)

    def test_conditions_set_back_are_reverted(self) -> None:
        effect = conditions_net_effect(
            [
                _change([_condition(PRO, variant="test")], [_condition()]),
                _change([_condition()], [_condition(PRO, variant="test")], minutes=17),
            ]
        )

        assert effect is not None
        self.assertEqual((effect.shape, effect.change_count), (ConditionsChangeShape.REVERTED, 2))
