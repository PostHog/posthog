from dataclasses import replace
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import ExperimentHealthFinding, ExperimentHealthFindingSeverity
from products.experiments.backend.health.checks.metric_uses_feature_flag_called import metric_uses_feature_flag_called
from products.experiments.backend.health.context import HealthContext, MetricEvents
from products.experiments.backend.health.skips import (
    NEEDS_METRIC_EVENT,
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    CheckSkip,
    not_applicable,
)
from products.experiments.backend.health.test.factories import DRAFT, ENDED, RUNNING_CONTEXT

Severity = ExperimentHealthFindingSeverity
FLAG_CALLS = MetricEvents(name="Flag calls", role="primary", events=("$feature_flag_called",))
CHECKOUT = MetricEvents(name="Checkout", role="secondary", events=("$feature_flag_called", "$pageview"))
REVENUE = MetricEvents(name="Revenue", role="primary", events=("$experiment_exposure", "purchase"))


def _context(*metrics: MetricEvents, **changes: Any) -> HealthContext:
    return replace(RUNNING_CONTEXT, metric_events=metrics, **changes)


class TestMetricUsesFeatureFlagCalled(TestCase):
    @parameterized.expand(
        [
            ("primary_metric", _context(FLAG_CALLS, REVENUE), Severity.WARNING),
            ("only_a_secondary_funnel_step", _context(CHECKOUT, REVENUE), Severity.INFO),
            ("draft", _context(FLAG_CALLS, **DRAFT, hours_since_launch=None), Severity.WARNING),
            ("other_events", _context(REVENUE), None),
            ("no_metric_reads_an_event", _context(), not_applicable(NEEDS_METRIC_EVENT)),
            ("ended", _context(FLAG_CALLS, **ENDED), not_applicable(NOT_AFTER_END)),
            ("archived", _context(FLAG_CALLS, archived=True), not_applicable(NOT_ON_ARCHIVED)),
            (
                "self_hosted",
                _context(FLAG_CALLS, flag_calls_kept_shorter=False),
                not_applicable("Runs only on PostHog Cloud"),
            ),
        ]
    )
    def test_outcome_follows_the_metrics_and_the_state(
        self, _name: str, ctx: HealthContext, expected: Severity | CheckSkip | None
    ) -> None:
        outcome = metric_uses_feature_flag_called(ctx)

        self.assertEqual(outcome.severity if isinstance(outcome, ExperimentHealthFinding) else outcome, expected)

    def test_names_each_metric_that_uses_the_event(self) -> None:
        finding = metric_uses_feature_flag_called(_context(FLAG_CALLS, REVENUE, CHECKOUT))

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(finding.title, '2 metrics use the event "$feature_flag_called"')
        self.assertEqual(
            dict(finding.evidence),
            {
                "metric_1": "Flag calls",
                "metric_1_role": "primary",
                "metric_2": "Checkout",
                "metric_2_role": "secondary",
            },
        )
        self.assertIn('the primary metric "Flag calls" and the secondary metric "Checkout"', finding.detail)
        self.assertNotIn("Revenue", finding.detail)
