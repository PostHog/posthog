from dataclasses import replace
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import ExperimentHealthFindingCode
from products.experiments.backend.health.checks.no_metric import no_metric
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.test.factories import RUNNING_CONTEXT


def _context(**changes: Any) -> HealthContext:
    return replace(RUNNING_CONTEXT, **{"primary_metric_count": 0, **changes})


class TestNoMetric(TestCase):
    @parameterized.expand(
        [
            ("running_without_metrics", _context(), True),
            ("ended_without_metrics", _context(is_running=False, has_ended=True), True),
            ("draft_without_metrics", _context(is_launched=False, is_running=False), False),
            ("secondary_metric_only", _context(secondary_metric_count=1), False),
            ("primary_metric_only", _context(primary_metric_count=1), False),
        ]
    )
    def test_no_metric(self, _name: str, ctx: HealthContext, expected: bool) -> None:
        finding = no_metric(ctx)

        self.assertEqual(finding.code if finding else None, ExperimentHealthFindingCode.NO_METRIC if expected else None)
