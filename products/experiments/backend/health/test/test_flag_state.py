from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import ExperimentHealthFindingCode, ExperimentHealthFindingSeverity
from products.experiments.backend.health.checks.flag_state import flag_state
from products.experiments.backend.health.context import ConditionSetTraffic, HealthContext, parse_flag_state
from products.experiments.backend.health.test.factories import DRAFT, ENDED, RUNNING, RUNNING_CONTEXT, Status

# The flag documents and cases of the `experimentWarning` test in
# frontend/src/scenes/experiments/experimentLogic.test.ts, so that both sides answer alike. A running
# experiment with a deleted flag is the exception: only the server reports it.
MULTIVARIANT = {
    "groups": [{"properties": [], "rollout_percentage": 100}],
    "multivariate": {
        "variants": [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
    },
}
SHIPPED_VARIANT = {
    "groups": [{"properties": [], "rollout_percentage": 100}],
    "multivariate": {
        "variants": [{"key": "control", "rollout_percentage": 0}, {"key": "test", "rollout_percentage": 100}]
    },
}
ZERO_ROLLOUT = {
    "groups": [{"properties": [], "rollout_percentage": 0}],
    "multivariate": {
        "variants": [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
    },
}
ZERO_ROLLOUT_SHIPPED_VARIANT = {
    "groups": [{"properties": [], "rollout_percentage": 0}],
    "multivariate": {
        "variants": [{"key": "control", "rollout_percentage": 0}, {"key": "test", "rollout_percentage": 100}]
    },
}
SHIPPED_TO_SOME = {
    "groups": [{"properties": [{"key": "email", "value": "x", "type": "person"}], "rollout_percentage": 100}],
    "multivariate": SHIPPED_VARIANT["multivariate"],
}


def _traffic(people_assigned_outside: int) -> ConditionSetTraffic:
    return ConditionSetTraffic(
        since=datetime(2026, 10, 12, 13, 4, tzinfo=UTC),
        team_timezone="Europe/Berlin",
        people_by_set={},
        calls=3 * people_assigned_outside,
        remotely_evaluated_calls=0,
        people_assigned_outside=people_assigned_outside,
    )


def _context(
    status: Status,
    *,
    active: bool,
    filters: dict[str, Any],
    deleted: bool = False,
    archived: bool = False,
    traffic: ConditionSetTraffic | None = None,
) -> HealthContext:
    return replace(
        RUNNING_CONTEXT,
        **status,
        is_paused=status["is_running"] and not active,
        archived=archived,
        flag=parse_flag_state(
            active=active,
            deleted=deleted,
            groups=filters.get("groups"),
            variants=(filters.get("multivariate") or {}).get("variants"),
        ),
        condition_set_traffic=traffic,
    )


class TestFlagState(TestCase):
    @parameterized.expand(
        [
            ("running_normal_rollout", _context(RUNNING, active=True, filters=MULTIVARIANT), None),
            (
                "running_flag_disabled",
                _context(RUNNING, active=False, filters=MULTIVARIANT),
                (ExperimentHealthFindingCode.FLAG_OFF_WHILE_RUNNING, "running_but_flag_disabled", None),
            ),
            (
                "running_single_variant_shipped",
                _context(RUNNING, active=True, filters=SHIPPED_VARIANT),
                (
                    ExperimentHealthFindingCode.VARIANT_SHIPPED_WHILE_RUNNING,
                    "running_but_single_variant_shipped",
                    "test",
                ),
            ),
            ("running_variant_shipped_to_some", _context(RUNNING, active=True, filters=SHIPPED_TO_SOME), None),
            (
                "running_zero_rollout",
                _context(RUNNING, active=True, filters=ZERO_ROLLOUT),
                (ExperimentHealthFindingCode.FLAG_OFF_WHILE_RUNNING, "running_but_no_rollout", None),
            ),
            (
                "running_zero_rollout_with_variants_assigned_outside",
                _context(RUNNING, active=True, filters=ZERO_ROLLOUT, traffic=_traffic(10)),
                (ExperimentHealthFindingCode.FLAG_OFF_WHILE_RUNNING, "assigned_outside_flag_service", None),
            ),
            (
                "running_zero_rollout_with_too_few_assigned_outside",
                _context(RUNNING, active=True, filters=ZERO_ROLLOUT, traffic=_traffic(9)),
                (ExperimentHealthFindingCode.FLAG_OFF_WHILE_RUNNING, "running_but_no_rollout", None),
            ),
            (
                "running_zero_rollout_before_shipped_variant",
                _context(RUNNING, active=True, filters=ZERO_ROLLOUT_SHIPPED_VARIANT),
                (ExperimentHealthFindingCode.FLAG_OFF_WHILE_RUNNING, "running_but_no_rollout", None),
            ),
            (
                "ended_flag_distributing_variants",
                _context(ENDED, active=True, filters=MULTIVARIANT),
                (ExperimentHealthFindingCode.FLAG_LIVE_AFTER_END, "ended_but_multiple_variants_rolled_out", None),
            ),
            ("ended_zero_rollout", _context(ENDED, active=True, filters=ZERO_ROLLOUT), None),
            ("ended_flag_disabled", _context(ENDED, active=False, filters=MULTIVARIANT), None),
            ("ended_single_variant_shipped", _context(ENDED, active=True, filters=SHIPPED_VARIANT), None),
            (
                "archived_ended_flag_distributing_variants",
                _context(ENDED, active=True, filters=MULTIVARIANT, archived=True),
                (ExperimentHealthFindingCode.FLAG_LIVE_AFTER_END, "ended_but_multiple_variants_rolled_out", None),
            ),
            (
                "draft_flag_distributing_variants",
                _context(DRAFT, active=True, filters=MULTIVARIANT),
                (
                    ExperimentHealthFindingCode.FLAG_LIVE_BEFORE_LAUNCH,
                    "not_started_but_multiple_variants_rolled_out",
                    None,
                ),
            ),
            (
                "archived_draft_flag_distributing_variants",
                _context(DRAFT, active=True, filters=MULTIVARIANT, archived=True),
                None,
            ),
            ("draft_zero_rollout", _context(DRAFT, active=True, filters=ZERO_ROLLOUT), None),
            ("draft_flag_disabled", _context(DRAFT, active=False, filters=MULTIVARIANT), None),
            (
                "running_deleted_flag",
                _context(RUNNING, active=True, filters=MULTIVARIANT, deleted=True),
                (ExperimentHealthFindingCode.FLAG_OFF_WHILE_RUNNING, "running_but_flag_deleted", None),
            ),
            (
                "running_deleted_flag_disabled_first",
                _context(RUNNING, active=False, filters=MULTIVARIANT, deleted=True),
                (ExperimentHealthFindingCode.FLAG_OFF_WHILE_RUNNING, "running_but_flag_deleted", None),
            ),
            ("ended_deleted_flag", _context(ENDED, active=True, filters=MULTIVARIANT, deleted=True), None),
            ("draft_deleted_flag", _context(DRAFT, active=True, filters=MULTIVARIANT, deleted=True), None),
            ("running_groups_are_null", _context(RUNNING, active=True, filters={**ZERO_ROLLOUT, "groups": None}), None),
            (
                "running_variants_are_null",
                _context(RUNNING, active=True, filters={**SHIPPED_VARIANT, "multivariate": {"variants": None}}),
                None,
            ),
            (
                "running_boolean_rollout_is_not_zero",
                _context(
                    RUNNING,
                    active=True,
                    filters={**ZERO_ROLLOUT, "groups": [{"properties": [], "rollout_percentage": False}]},
                ),
                None,
            ),
        ]
    )
    def test_flag_state(
        self, _name: str, ctx: HealthContext, expected: tuple[ExperimentHealthFindingCode, str, str | None] | None
    ) -> None:
        finding = flag_state(ctx)

        if expected is None:
            self.assertIsNone(finding)
            return
        assert finding is not None
        code, subcode, variant_key = expected
        self.assertEqual((finding.code, finding.subcode), (code, subcode))
        self.assertEqual(finding.evidence.get("variant_key"), variant_key)

    def test_variants_assigned_outside_the_flag_service_are_info(self) -> None:
        finding = flag_state(_context(RUNNING, active=True, filters=ZERO_ROLLOUT, traffic=_traffic(1234)))

        assert finding is not None
        self.assertEqual(
            (finding.severity, finding.title, finding.detail, dict(finding.evidence)),
            (
                ExperimentHealthFindingSeverity.INFO,
                "Variants are assigned outside PostHog",
                "The linked feature flag has a 0% rollout, so PostHog assigns no variants. But 1,234 users got a "
                "variant since October 12, 2026 at 4:04 PM CEST from flag calls that PostHog didn't evaluate, so your "
                "own code assigns the variants, directly or through a bootstrap. These users count in the results. "
                "The flag's release conditions and variant split don't decide who gets which variant. If PostHog "
                "should assign the variants, increase the rollout and stop assigning them in your code.",
                {"people_assigned_outside": 1234, "assigned_outside_since": "2026-10-12T14:04:00+00:00"},
            ),
        )
