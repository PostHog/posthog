from dataclasses import replace
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import ExperimentHealthFinding, ExperimentHealthFindingCode
from products.experiments.backend.health.checks.no_metric import no_metric
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.skips import RUNS_AFTER_LAUNCH, CheckSkip, not_applicable
from products.experiments.backend.health.test.factories import RUNNING_CONTEXT

NO_METRIC = ExperimentHealthFindingCode.NO_METRIC


def _context(**changes: Any) -> HealthContext:
    return replace(RUNNING_CONTEXT, **{"primary_metric_count": 0, **changes})


class TestNoMetric(TestCase):
    @parameterized.expand(
        [
            ("running_without_metrics", _context(), NO_METRIC),
            ("ended_without_metrics", _context(is_running=False, has_ended=True), NO_METRIC),
            (
                "draft_without_metrics",
                _context(is_launched=False, is_running=False),
                not_applicable(RUNS_AFTER_LAUNCH),
            ),
            ("secondary_metric_only", _context(secondary_metric_count=1), None),
            ("primary_metric_only", _context(primary_metric_count=1), None),
        ]
    )
    def test_no_metric(
        self, _name: str, ctx: HealthContext, expected: ExperimentHealthFindingCode | CheckSkip | None
    ) -> None:
        outcome = no_metric(ctx)

        self.assertEqual(outcome.code if isinstance(outcome, ExperimentHealthFinding) else outcome, expected)
