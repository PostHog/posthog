from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import ExperimentHealthFindingCode
from products.experiments.backend.health.checks.flag_variants import flag_variants_mismatch
from products.experiments.backend.health.context import HealthContext, parse_flag_state

EVEN_SPLIT = [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
NO_CONTROL_SPLIT = [{"key": "a", "rollout_percentage": 50}, {"key": "b", "rollout_percentage": 50}]

RUNNING = {"is_launched": True, "is_running": True, "has_ended": False}
ENDED = {"is_launched": True, "is_running": False, "has_ended": True}
DRAFT = {"is_launched": False, "is_running": False, "has_ended": False}


def _context(
    status: dict[str, bool],
    *,
    variants: list[dict[str, Any]] | None = EVEN_SPLIT,
    baseline: str | None = None,
    deleted: bool = False,
    archived: bool = False,
) -> HealthContext:
    return HealthContext(
        **status,
        is_paused=False,
        archived=archived,
        flag=parse_flag_state(
            active=True,
            deleted=deleted,
            groups=[{"properties": [], "rollout_percentage": 100}],
            variants=variants,
        ),
        baseline_variant_key=baseline,
        primary_metric_count=1,
        secondary_metric_count=0,
        exposures=None,
        split_history=None,
        condition_set_traffic=None,
        excluded_variant_keys=frozenset(),
    )


class TestFlagVariantsMismatch(TestCase):
    @parameterized.expand(
        [
            ("running_flag_without_variants", _context(RUNNING, variants=None), "flag_has_no_variants"),
            ("draft_flag_without_variants", _context(DRAFT, variants=None), None),
            ("running_baseline_not_a_variant", _context(RUNNING, baseline="holdout"), "no_control_variant"),
            ("draft_baseline_not_a_variant", _context(DRAFT, baseline="holdout"), "no_control_variant"),
            ("baseline_is_a_variant", _context(RUNNING, baseline="test"), None),
            ("no_baseline_and_no_control_variant", _context(RUNNING, variants=NO_CONTROL_SPLIT), None),
            ("ended_flag_changed_to_boolean", _context(ENDED, variants=None), None),
            ("archived_draft_baseline_not_a_variant", _context(DRAFT, baseline="holdout", archived=True), None),
            ("deleted_flag_without_variants", _context(RUNNING, variants=None, deleted=True), None),
        ]
    )
    def test_flag_variants_mismatch(self, _name: str, ctx: HealthContext, expected_subcode: str | None) -> None:
        finding = flag_variants_mismatch(ctx)

        if expected_subcode is None:
            self.assertIsNone(finding)
            return
        assert finding is not None
        self.assertEqual(
            (finding.code, finding.subcode), (ExperimentHealthFindingCode.FLAG_VARIANTS_MISMATCH, expected_subcode)
        )
        self.assertEqual(finding.evidence.get("baseline_variant_key"), ctx.baseline_variant_key)
