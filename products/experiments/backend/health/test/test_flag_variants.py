from dataclasses import replace
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import ExperimentHealthFinding, ExperimentHealthFindingCode
from products.experiments.backend.health.checks.flag_variants import flag_variants_mismatch
from products.experiments.backend.health.context import HealthContext, parse_flag_state
from products.experiments.backend.health.skips import (
    FLAG_DELETED,
    NEEDS_VARIANTS,
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    CheckSkip,
    not_applicable,
)
from products.experiments.backend.health.test.factories import DRAFT, ENDED, RUNNING, RUNNING_CONTEXT, Status

EVEN_SPLIT = [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
NO_CONTROL_SPLIT = [{"key": "a", "rollout_percentage": 50}, {"key": "b", "rollout_percentage": 50}]


def _context(
    status: Status,
    *,
    variants: list[dict[str, Any]] | None = EVEN_SPLIT,
    baseline: str | None = None,
    deleted: bool = False,
    archived: bool = False,
) -> HealthContext:
    return replace(
        RUNNING_CONTEXT,
        **status,
        archived=archived,
        flag=parse_flag_state(
            active=True,
            deleted=deleted,
            groups=[{"properties": [], "rollout_percentage": 100}],
            variants=variants,
        ),
        baseline_variant_key=baseline,
    )


class TestFlagVariantsMismatch(TestCase):
    @parameterized.expand(
        [
            ("running_flag_without_variants", _context(RUNNING, variants=None), "flag_has_no_variants"),
            ("draft_flag_without_variants", _context(DRAFT, variants=None), not_applicable(NEEDS_VARIANTS)),
            ("running_baseline_not_a_variant", _context(RUNNING, baseline="holdout"), "no_control_variant"),
            ("draft_baseline_not_a_variant", _context(DRAFT, baseline="holdout"), "no_control_variant"),
            ("baseline_is_a_variant", _context(RUNNING, baseline="test"), None),
            ("no_baseline_and_no_control_variant", _context(RUNNING, variants=NO_CONTROL_SPLIT), None),
            ("ended_flag_changed_to_boolean", _context(ENDED, variants=None), not_applicable(NOT_AFTER_END)),
            (
                "archived_draft_baseline_not_a_variant",
                _context(DRAFT, baseline="holdout", archived=True),
                not_applicable(NOT_ON_ARCHIVED),
            ),
            (
                "deleted_flag_without_variants",
                _context(RUNNING, variants=None, deleted=True),
                not_applicable(FLAG_DELETED),
            ),
        ]
    )
    def test_flag_variants_mismatch(self, _name: str, ctx: HealthContext, expected: str | CheckSkip | None) -> None:
        outcome = flag_variants_mismatch(ctx)

        if not isinstance(outcome, ExperimentHealthFinding) or not isinstance(expected, str):
            self.assertEqual(outcome, expected)
            return
        self.assertEqual(
            (outcome.code, outcome.subcode), (ExperimentHealthFindingCode.FLAG_VARIANTS_MISMATCH, expected)
        )
        self.assertEqual(outcome.evidence.get("baseline_variant_key"), ctx.baseline_variant_key)
