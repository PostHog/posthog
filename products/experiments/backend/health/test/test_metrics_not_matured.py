from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest import TestCase

from django.utils import timezone

from parameterized import parameterized

from products.experiments.backend.facade.api import get_experiment_health
from products.experiments.backend.facade.contracts import (
    ExperimentHealthCheckKey,
    ExperimentHealthCheckStatus,
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthReaderAccess,
)
from products.experiments.backend.health.checks.metrics_not_matured import metrics_not_matured
from products.experiments.backend.health.context import HealthContext, MetricWindow
from products.experiments.backend.health.metric_windows import metric_window
from products.experiments.backend.health.skips import NOT_AFTER_END, NOT_ON_ARCHIVED, RUNS_AFTER_LAUNCH, CheckSkip
from products.experiments.backend.health.test.factories import DRAFT, ENDED, RUNNING_CONTEXT
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.feature_flags.backend.models.feature_flag import FeatureFlag

Status = ExperimentHealthCheckStatus
NO_QUERIES = ExperimentHealthReaderAccess(
    can_read_flag_history=False, can_query_events=False, denied_event_properties=frozenset()
)
LAUNCHED_AT = datetime(2026, 10, 1, 12, tzinfo=UTC)
PURCHASE = {"kind": "EventsNode", "event": "purchase"}
NO_WINDOW = {"kind": "ExperimentMetric", "metric_type": "funnel", "series": [PURCHASE]}
THREE_DAYS = {**NO_WINDOW, "conversion_window": 3, "conversion_window_unit": "day"}
FOUR_DAYS = {**NO_WINDOW, "conversion_window": 4, "conversion_window_unit": "day"}
WINDOW_WITHOUT_UNIT = {**NO_WINDOW, "conversion_window": 4}
MEAN_FOUR_DAYS = {
    "kind": "ExperimentMetric",
    "metric_type": "mean",
    "source": PURCHASE,
    "conversion_window": 4,
    "conversion_window_unit": "day",
}
RETENTION = {
    "kind": "ExperimentMetric",
    "metric_type": "retention",
    "start_event": PURCHASE,
    "completion_event": PURCHASE,
    "start_handling": "first_seen",
    "retention_window_start": 1,
    "retention_window_end": 14,
    "retention_window_unit": "day",
    "conversion_window": 1,
    "conversion_window_unit": "hour",
}


def _window(name: str, metric: dict[str, Any]) -> MetricWindow:
    window = metric_window(name=name, definition=metric, start_date=LAUNCHED_AT)
    assert window is not None
    return window


def _context(metrics: list[tuple[str, dict[str, Any]]], *, hours_since_launch: float = 72) -> HealthContext:
    return replace(
        RUNNING_CONTEXT,
        only_count_matured_users=True,
        hours_since_launch=hours_since_launch,
        primary_metric_count=len(metrics),
        primary_metric_windows=tuple(_window(name, metric) for name, metric in metrics),
    )


class TestMetricsNotMatured(TestCase):
    @parameterized.expand(
        [
            ("one_primary_held_back", [("Checkout", FOUR_DAYS)], 72, True),
            ("mean_metric_held_back", [("Revenue", MEAN_FOUR_DAYS)], 72, True),
            ("every_primary_held_back", [("Checkout", FOUR_DAYS), ("Return", RETENTION)], 72, True),
            ("age_below_the_window", [("Checkout", THREE_DAYS)], 71.9, True),
            ("age_equal_to_the_window", [("Checkout", THREE_DAYS)], 72, False),
            ("retention_uses_its_own_window_not_the_conversion_window", [("Return", RETENTION)], 13 * 24, True),
            (
                "retention_uses_its_own_unit",
                [("Return", {**RETENTION, "retention_window_unit": "hour"})],
                14,
                False,
            ),
            ("window_without_a_unit", [("Checkout", WINDOW_WITHOUT_UNIT)], 72, False),
            ("no_window_before_a_future_start_date", [("Signup", NO_WINDOW)], -1, False),
            ("one_of_two_without_a_window", [("Checkout", FOUR_DAYS), ("Signup", NO_WINDOW)], 72, False),
            ("one_of_two_past_its_window", [("Checkout", FOUR_DAYS), ("Signup", THREE_DAYS)], 72, False),
        ]
    )
    def test_warns_only_when_every_primary_metric_is_held_back(
        self, _name: str, metrics: list[tuple[str, dict[str, Any]]], hours_since_launch: float, expected: bool
    ) -> None:
        outcome = metrics_not_matured(_context(metrics, hours_since_launch=hours_since_launch))

        self.assertEqual(isinstance(outcome, ExperimentHealthFinding), expected)
        if not expected:
            self.assertIsNone(outcome)

    def test_names_each_metric_and_the_time_its_first_users_count(self) -> None:
        outcome = metrics_not_matured(_context([("Return", RETENTION), ("Checkout", FOUR_DAYS)]))

        assert isinstance(outcome, ExperimentHealthFinding)
        self.assertEqual(
            (outcome.code, outcome.subcode, outcome.reason, outcome.severity, outcome.actions),
            (ExperimentHealthFindingCode.METRICS_NOT_MATURED, None, None, ExperimentHealthFindingSeverity.WARNING, ()),
        )
        self.assertIn(
            'The first users can count for "Return" on October 15, 2026 at 2:00 PM CEST and for "Checkout" on '
            "October 5, 2026 at 2:00 PM CEST.",
            outcome.detail,
        )
        self.assertEqual(
            outcome.evidence, {"hours_since_launch": 72, "first_users_count_at": "2026-10-05T12:00:00+00:00"}
        )

    @parameterized.expand(
        [
            (
                "setting_off",
                {"only_count_matured_users": False},
                Status.NOT_APPLICABLE,
                'Runs when "Require completed conversion or retention window" is on',
            ),
            ("draft", DRAFT, Status.NOT_APPLICABLE, RUNS_AFTER_LAUNCH),
            ("ended", ENDED, Status.NOT_APPLICABLE, NOT_AFTER_END),
            ("archived", {"archived": True, **ENDED}, Status.NOT_APPLICABLE, NOT_ON_ARCHIVED),
            (
                "no_primary_metric",
                {"primary_metric_count": 0, "primary_metric_windows": None},
                Status.NOT_APPLICABLE,
                "Runs once the experiment has a metric",
            ),
            (
                "only_legacy_primary_metrics",
                {"primary_metric_windows": ()},
                Status.NOT_APPLICABLE,
                "Runs once the experiment has a metric in the current format",
            ),
            (
                "windows_not_loaded",
                {"primary_metric_windows": None},
                Status.NOT_CHECKED,
                "Couldn't check because the primary metric windows couldn't be read",
            ),
        ]
    )
    def test_says_why_it_did_not_look(self, _name: str, changes: dict[str, Any], status: Status, reason: str) -> None:
        outcome = metrics_not_matured(replace(_context([("Checkout", FOUR_DAYS)]), **changes))

        assert isinstance(outcome, CheckSkip)
        self.assertEqual((outcome.status, outcome.reason), (status, reason))


class TestMetricsNotMaturedFromStoredMetrics(BaseTest):
    @parameterized.expand(
        [
            ("saved_primary_held_back", [], [], FOUR_DAYS, Status.FINDING, "Checkout funnel"),
            (
                "a_secondary_past_its_window_does_not_clear_the_primaries",
                [FOUR_DAYS],
                [NO_WINDOW],
                None,
                Status.FINDING,
                "purchase conversion",
            ),
            ("only_a_secondary_held_back", [NO_WINDOW], [FOUR_DAYS], None, Status.PASSED, None),
            ("a_primary_that_does_not_parse", [{"metric_type": "funnel"}], [], None, Status.NOT_CHECKED, None),
        ]
    )
    def test_reads_the_windows_of_the_stored_primary_metrics(
        self,
        _name: str,
        primary: list[dict[str, Any]],
        secondary: list[dict[str, Any]],
        saved_primary: dict[str, Any] | None,
        expected: Status,
        expected_metric: str | None,
    ) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="checkout-flag",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        experiment = Experiment.objects.create(
            team=self.team,
            name="checkout",
            feature_flag=flag,
            start_date=timezone.now() - timedelta(days=3),
            only_count_matured_users=True,
            metrics=[{**metric, "uuid": f"primary-{index}"} for index, metric in enumerate(primary)],
            metrics_secondary=[{**metric, "uuid": f"secondary-{index}"} for index, metric in enumerate(secondary)],
        )
        if saved_primary is not None:
            saved_metric = ExperimentSavedMetric.objects.create(
                team=self.team, name="Checkout funnel", query={**saved_primary, "uuid": "saved-primary"}
            )
            ExperimentToSavedMetric.objects.create(
                experiment=experiment, saved_metric=saved_metric, metadata={"type": "primary"}
            )

        health = get_experiment_health(
            team_id=self.team.id, experiment_id=experiment.id, reader_access=NO_QUERIES, user=self.user
        )

        check = next(check for check in health.checks if check.key == ExperimentHealthCheckKey.METRICS_NOT_MATURED)
        self.assertEqual(check.status, expected)
        finding = next(
            (finding for finding in health.findings if finding.code == ExperimentHealthFindingCode.METRICS_NOT_MATURED),
            None,
        )
        self.assertEqual(finding is not None, expected == Status.FINDING)
        if finding:
            self.assertIn(f'"{expected_metric}"', finding.detail)
