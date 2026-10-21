from dataclasses import replace
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import ExperimentHealthFindingSeverity
from products.experiments.backend.health.checks.metric_event_not_ingested import metric_event_not_ingested
from products.experiments.backend.health.context import HealthContext, MetricEvents
from products.experiments.backend.health.test.factories import DRAFT, ENDED, RUNNING_CONTEXT

Severity = ExperimentHealthFindingSeverity
REVENUE = MetricEvents(name="Revenue", role="primary", events=("purchase",))
SIGNUPS = MetricEvents(name="Signups", role="secondary", events=("signup",))


def _context(*metrics: MetricEvents, received: dict[str, bool], **changes: Any) -> HealthContext:
    return replace(RUNNING_CONTEXT, metric_events=metrics, events_received=received, **changes)


class TestMetricEventNotIngested(TestCase):
    @parameterized.expand(
        [
            ("draft", _context(REVENUE, received={"purchase": False}, **DRAFT, hours_since_launch=None), Severity.INFO),
            (
                "first_day_after_launch",
                _context(REVENUE, received={"purchase": False}, hours_since_launch=23.9),
                Severity.INFO,
            ),
            (
                "a_day_after_launch",
                _context(REVENUE, received={"purchase": False}, hours_since_launch=24),
                Severity.WARNING,
            ),
            ("only_a_secondary_metric", _context(SIGNUPS, received={"signup": False}), Severity.INFO),
            ("received", _context(REVENUE, received={"purchase": True}), None),
            ("a_name_without_a_definition_is_left_out", _context(REVENUE, received={}), None),
            ("ended", _context(REVENUE, received={"purchase": False}, **ENDED), None),
            ("archived", _context(REVENUE, received={"purchase": False}, archived=True), None),
        ]
    )
    def test_severity_follows_the_state(self, _name: str, ctx: HealthContext, expected: Severity | None) -> None:
        finding = metric_event_not_ingested(ctx)

        self.assertEqual(finding.severity if finding else None, expected)

    def test_names_each_metric_and_its_missing_events(self) -> None:
        funnel = MetricEvents(name="Checkout", role="primary", events=("cart", "pay", "view"))
        ctx = _context(funnel, SIGNUPS, received={"cart": False, "pay": True, "view": False, "signup": False})

        finding = metric_event_not_ingested(ctx)

        assert finding is not None
        self.assertEqual(finding.title, "2 metrics use events this project hasn't received")
        self.assertEqual(
            dict(finding.evidence),
            {
                "metric_1": "Checkout",
                "metric_1_role": "primary",
                "metric_1_events": "cart, view",
                "metric_2": "Signups",
                "metric_2_role": "secondary",
                "metric_2_events": "signup",
            },
        )
        self.assertIn('the primary metric "Checkout" uses "cart" and "view"', finding.detail)
        self.assertIn('the secondary metric "Signups" uses "signup"', finding.detail)
        self.assertNotIn('"pay"', finding.detail)
