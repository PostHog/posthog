from dataclasses import replace
from datetime import timedelta
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
from products.experiments.backend.health.checks.early_significance import BELOW_DETECTABLE_EFFECT, early_significance
from products.experiments.backend.health.context import HealthContext, PrimaryMetric
from products.experiments.backend.health.skips import CheckSkip
from products.experiments.backend.health.test.factories import ENDED, RUNNING_CONTEXT
from products.experiments.backend.logic.result_stats import BaselineStats, Interval, MetricResultStats, VariantStats
from products.experiments.backend.metric_calculation.config import build_primary_calculation_configs
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.feature_flags.backend.models.feature_flag import FeatureFlag

Status = ExperimentHealthCheckStatus
NO_QUERIES = ExperimentHealthReaderAccess(
    can_read_flag_history=False, can_query_events=False, denied_event_properties=frozenset()
)
FUNNEL = {"kind": "ExperimentMetric", "metric_type": "funnel", "series": [{"kind": "EventsNode", "event": "purchase"}]}


def _context(
    variants: list[tuple[str, int, float, bool | None]],
    *,
    baseline: tuple[int, int] = (1000, 100),
    manual_running_time: bool = False,
    **changes: Any,
) -> HealthContext:
    control_samples, control_conversions = baseline
    control_rate = control_conversions / control_samples
    result = MetricResultStats(
        method="bayesian",
        baseline=BaselineStats(key="control", number_of_samples=control_samples, mean=control_rate),
        # The raw rate equals the control's, so only the analysis interval carries the difference, as under CUPED.
        variants=tuple(
            VariantStats(
                key=key,
                number_of_samples=samples,
                mean=control_rate,
                interval=Interval(low=difference - 0.15, high=difference + 0.15),
                chance_to_win=None,
                p_value=None,
                significant=significant,
            )
            for key, samples, difference, significant in variants
        ),
    )
    metric = PrimaryMetric(
        name="Checkout",
        is_funnel=True,
        minimum_detectable_effect=30,
        manual_running_time=manual_running_time,
        result=result,
    )
    return replace(RUNNING_CONTEXT, primary_metric=metric, **changes)


# A 10% control rate on 1,000 users per variant detects differences of about 38% or more.
SMALL_SIGNIFICANT_LIFT = _context([("test", 1000, 0.2, True)])


class TestEarlySignificance(TestCase):
    @parameterized.expand(
        [
            ("significant_and_smaller_than_detectable", SMALL_SIGNIFICANT_LIFT, "test"),
            ("significant_and_larger_than_detectable", _context([("test", 1000, -0.5, True)]), None),
            ("not_significant", _context([("test", 1000, 0.2, False)]), None),
            ("analysis_stopped", _context([("test", 1000, 0.2, None)]), None),
            ("sample_reached_the_plan", _context([("test", 20000, 0.06, True)], baseline=(20000, 2000)), None),
            (
                "uneven_split_past_the_planned_total",
                _context([("test", 500, 0.34, True)], baseline=(9000, 900)),
                None,
            ),
            (
                "names_the_variant_below_detectable",
                _context([("large", 1000, 0.5, True), ("small", 1000, 0.2, True)]),
                "small",
            ),
        ]
    )
    def test_notes_a_significant_difference_the_sample_cannot_detect(
        self, _name: str, ctx: HealthContext, expected_variant: str | None
    ) -> None:
        finding = early_significance(ctx)

        self.assertEqual(
            finding.evidence["variant"] if isinstance(finding, ExperimentHealthFinding) else finding, expected_variant
        )

    def test_states_the_analysis_difference_and_the_planned_sizes(self) -> None:
        finding = early_significance(SMALL_SIGNIFICANT_LIFT)

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(
            (finding.code, finding.subcode, finding.severity),
            (
                ExperimentHealthFindingCode.EARLY_SIGNIFICANCE,
                BELOW_DETECTABLE_EFFECT,
                ExperimentHealthFindingSeverity.INFO,
            ),
        )
        self.assertEqual(
            finding.evidence,
            {
                "variant": "test",
                "observed_effect": 20.0,
                "detectable_effect": 37.9,
                "minimum_detectable_effect": 30,
                "samples": 2000,
                "planned_samples": 3201,
            },
        )

    @parameterized.expand(
        [
            ("ended", replace(SMALL_SIGNIFICANT_LIFT, **ENDED), Status.NOT_APPLICABLE),
            ("unreadable_results", replace(SMALL_SIGNIFICANT_LIFT, primary_metric=None), Status.NOT_CHECKED),
            (
                "mean_metric",
                replace(
                    SMALL_SIGNIFICANT_LIFT,
                    primary_metric=PrimaryMetric(
                        name="Revenue",
                        is_funnel=False,
                        minimum_detectable_effect=30,
                        manual_running_time=False,
                        result=None,
                    ),
                ),
                Status.NOT_APPLICABLE,
            ),
            (
                "manual_running_time",
                _context([("test", 1000, 0.2, True)], manual_running_time=True),
                Status.NOT_APPLICABLE,
            ),
            ("under_50_users", _context([("test", 20, 0.2, True)], baseline=(20, 2)), Status.NOT_APPLICABLE),
            (
                "no_control_conversions",
                _context([("test", 1000, 0.2, True)], baseline=(1000, 0)),
                Status.NOT_APPLICABLE,
            ),
        ]
    )
    def test_says_why_it_did_not_look(self, _name: str, ctx: HealthContext, expected: Status) -> None:
        outcome = early_significance(ctx)

        self.assertEqual(outcome.status if isinstance(outcome, CheckSkip) else outcome, expected)


class TestEarlySignificanceFromStoredResults(BaseTest):
    @parameterized.expand(
        [
            (
                "inline_metric_and_the_experiments_effect",
                False,
                True,
                {"minimum_detectable_effect": 20},
                15,
                Status.FINDING,
                20,
            ),
            ("inline_metric_and_the_teams_default_effect", False, True, {}, 15, Status.FINDING, 15),
            ("inline_metric_and_the_product_default_effect", False, True, {}, None, Status.FINDING, 30),
            ("shared_metric", True, True, {}, None, Status.FINDING, 30),
            ("result_of_an_earlier_configuration", False, False, {}, None, Status.NOT_APPLICABLE, None),
            (
                "manual_running_time",
                False,
                True,
                {"exposure_estimate_config": {"conversionRateInputType": "manual"}},
                None,
                Status.NOT_APPLICABLE,
                None,
            ),
        ]
    )
    def test_reads_the_primary_metrics_current_result(
        self,
        _name: str,
        shared: bool,
        under_current_key: bool,
        running_time_calculation: dict[str, Any],
        team_effect: int | None,
        expected: Status,
        expected_effect: int | None,
    ) -> None:
        if team_effect is not None:
            TeamExperimentsConfig.objects.create(team=self.team, default_minimum_detectable_effect=team_effect)
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
        launched_at = timezone.now() - timedelta(days=3)
        experiment = Experiment.objects.create(
            team=self.team,
            name="checkout",
            feature_flag=flag,
            start_date=launched_at,
            metrics=[] if shared else [{**FUNNEL, "uuid": "checkout-funnel"}],
            running_time_calculation=running_time_calculation,
        )
        if shared:
            saved_metric = ExperimentSavedMetric.objects.create(
                team=self.team, name="Checkout funnel", query={**FUNNEL, "uuid": "checkout-funnel"}
            )
            ExperimentToSavedMetric.objects.create(
                experiment=experiment, saved_metric=saved_metric, metadata={"type": "primary"}
            )
        calculation_key = build_primary_calculation_configs(experiment)[0].calculation_key()
        ExperimentMetricResult.objects.create(
            experiment=experiment,
            metric_uuid="checkout-funnel",
            fingerprint=calculation_key if under_current_key else "0" * 64,
            query_from=launched_at,
            query_to=timezone.now(),
            completed_at=timezone.now(),
            status=ExperimentMetricResult.Status.COMPLETED,
            result={
                "baseline": {"key": "control", "number_of_samples": 1000, "sum": 100, "sum_squares": 100},
                "variant_results": [
                    {
                        "key": "test",
                        "method": "bayesian",
                        "number_of_samples": 1000,
                        "sum": 120,
                        "sum_squares": 120,
                        "credible_interval": [0.05, 0.35],
                        "chance_to_win": 0.98,
                        "significant": True,
                    }
                ],
            },
        )

        health = get_experiment_health(team_id=self.team.id, experiment_id=experiment.id, reader_access=NO_QUERIES)

        check = next(check for check in health.checks if check.key == ExperimentHealthCheckKey.EARLY_SIGNIFICANCE)
        finding = next(
            (finding for finding in health.findings if finding.code == ExperimentHealthFindingCode.EARLY_SIGNIFICANCE),
            None,
        )
        self.assertEqual(
            (check.status, finding.evidence["minimum_detectable_effect"] if finding else None),
            (expected, expected_effect),
        )
        if finding:
            self.assertIn('"Checkout funnel"' if shared else '"purchase conversion"', finding.detail)
