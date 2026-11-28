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
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthReaderAccess,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.checks.early_significance import early_significance
from products.experiments.backend.health.checks.result_ready import (
    REPORTED_BY_EARLY_SIGNIFICANCE,
    STAYED_SIGNIFICANT,
    TARGET_REACHED_NOT_SIGNIFICANT,
    result_ready,
    result_ready_values,
)
from products.experiments.backend.health.context import HealthContext, PrimaryMetric
from products.experiments.backend.health.skips import RUNS_AFTER_LAUNCH, CheckSkip, not_applicable
from products.experiments.backend.health.test.factories import DRAFT, ENDED, RUNNING_CONTEXT
from products.experiments.backend.logic.result_stats import BaselineStats, Interval, MetricResultStats, VariantStats
from products.experiments.backend.metric_calculation.config import build_primary_calculation_configs
from products.experiments.backend.metric_calculation.results import SignificanceHistory, _recalc_fingerprint
from products.experiments.backend.models.experiment import Experiment, ExperimentMetricResult
from products.experiments.backend.running_time_target import RunningTimeTarget
from products.feature_flags.backend.models.feature_flag import FeatureFlag

Status = ExperimentHealthCheckStatus
NO_QUERIES = ExperimentHealthReaderAccess(
    can_read_flag_history=False,
    can_query_events=False,
    denied_event_properties=frozenset(),
    restricted_properties=frozenset(),
)
CURRENT_UNTIL = datetime(2026, 11, 20, 8, tzinfo=UTC)


def _context(
    variants: list[tuple[str, float, bool | None]],
    *,
    significant_days: dict[str, float] | None = None,
    planned_samples: int | None = 3201,
    is_funnel: bool = True,
    **changes: Any,
) -> HealthContext:
    # 1,000 users per variant at a 10% control rate detect differences of about 38% or more.
    result = MetricResultStats(
        method="bayesian",
        baseline=BaselineStats(key="control", number_of_samples=1000, mean=0.1),
        variants=tuple(
            VariantStats(
                key=key,
                number_of_samples=1000,
                mean=0.1,
                interval=Interval(low=difference - 0.15, high=difference + 0.15),
                chance_to_win=None,
                p_value=None,
                significant=significant,
            )
            for key, difference, significant in variants
        ),
    )
    metric = PrimaryMetric(
        name="Checkout",
        is_funnel=is_funnel,
        target=RunningTimeTarget(minimum_detectable_effect=30, recommended_sample_size=planned_samples),
        result=result,
        significance=SignificanceHistory(
            current_until=CURRENT_UNTIL,
            significant_since={
                key: CURRENT_UNTIL - timedelta(days=days) for key, days in (significant_days or {}).items()
            },
        ),
    )
    return replace(RUNNING_CONTEXT, primary_metric=metric, **changes)


LARGE_LIFT_FOR_5_DAYS = _context([("test", 0.5, True)], significant_days={"test": 5.5})
NOT_SIGNIFICANT_AT_THE_PLAN = _context([("test", 0.05, False)], planned_samples=2000)
# A difference below what the sample detects, before the plan, which `early_significance` reports.
SMALL_LIFT_FOR_5_DAYS = _context([("test", 0.2, True)], significant_days={"test": 5})


class TestResultReady(TestCase):
    @parameterized.expand(
        [
            ("significant_for_3_days", _context([("test", 0.5, True)], significant_days={"test": 3}), "test"),
            ("significant_for_less_than_3_days", _context([("test", 0.5, True)], significant_days={"test": 2.9}), None),
            (
                "names_the_variant_significant_longest",
                _context([("a", 0.5, True), ("b", -0.5, True)], significant_days={"a": 4, "b": 6}),
                "b",
            ),
            (
                "small_difference_at_the_plan",
                _context([("test", 0.2, True)], significant_days={"test": 5}, planned_samples=2000),
                "test",
            ),
            (
                "small_difference_on_a_mean_metric",
                _context([("test", 0.2, True)], significant_days={"test": 5}, is_funnel=False),
                "test",
            ),
        ]
    )
    def test_finds_a_variant_that_stayed_significant(
        self, _name: str, ctx: HealthContext, expected_variant: str | None
    ) -> None:
        finding = result_ready(ctx)

        self.assertEqual(
            (finding.subcode, finding.evidence["variant"]) if isinstance(finding, ExperimentHealthFinding) else finding,
            (STAYED_SIGNIFICANT, expected_variant) if expected_variant else None,
        )

    @parameterized.expand(
        [
            ("not_significant_at_the_plan", NOT_SIGNIFICANT_AT_THE_PLAN, True),
            ("below_the_plan", _context([("test", 0.05, False)]), False),
            ("no_plan", _context([("test", 0.05, False)], planned_samples=None), False),
            (
                "a_variant_without_an_analysis",
                _context([("test", 0.05, False), ("other", 0.0, None)], planned_samples=3000),
                False,
            ),
            (
                "a_variant_significant_for_a_day",
                _context([("test", 0.5, True)], significant_days={"test": 1}, planned_samples=2000),
                False,
            ),
        ]
    )
    def test_finds_the_plan_reached_without_a_significant_variant(
        self, _name: str, ctx: HealthContext, expected: bool
    ) -> None:
        finding = result_ready(ctx)

        self.assertEqual(
            finding.subcode if isinstance(finding, ExperimentHealthFinding) else finding,
            TARGET_REACHED_NOT_SIGNIFICANT if expected else None,
        )

    def test_steps_back_while_early_significance_asks_to_wait(self) -> None:
        self.assertEqual(
            (
                isinstance(early_significance(SMALL_LIFT_FOR_5_DAYS), ExperimentHealthFinding),
                result_ready(SMALL_LIFT_FOR_5_DAYS),
            ),
            (True, not_applicable(REPORTED_BY_EARLY_SIGNIFICANCE)),
        )

    @parameterized.expand(
        [
            ("ended", replace(LARGE_LIFT_FOR_5_DAYS, **ENDED), Status.NOT_APPLICABLE, None),
            ("archived", replace(LARGE_LIFT_FOR_5_DAYS, archived=True), Status.NOT_APPLICABLE, None),
            ("draft", replace(LARGE_LIFT_FOR_5_DAYS, **DRAFT), Status.NOT_APPLICABLE, RUNS_AFTER_LAUNCH),
            # A draft at launch has no stored results to load, so the launch keeps "Runs after launch".
            ("unreadable_results", replace(LARGE_LIFT_FOR_5_DAYS, primary_metric=None), Status.NOT_CHECKED, None),
            (
                "no_results",
                replace(
                    LARGE_LIFT_FOR_5_DAYS,
                    primary_metric=PrimaryMetric(
                        name="Checkout",
                        is_funnel=True,
                        target=RunningTimeTarget(minimum_detectable_effect=30, recommended_sample_size=None),
                        result=None,
                    ),
                ),
                Status.NOT_APPLICABLE,
                None,
            ),
        ]
    )
    def test_says_why_it_did_not_look(
        self, _name: str, ctx: HealthContext, expected: Status, expected_reason: str | None
    ) -> None:
        outcome = result_ready(ctx)

        assert isinstance(outcome, CheckSkip)
        self.assertEqual(outcome.status, expected)
        if expected_reason:
            self.assertEqual(outcome.reason, expected_reason)

    @parameterized.expand(
        [
            (
                "stayed_significant",
                LARGE_LIFT_FOR_5_DAYS,
                'The variant "test" has been significant for 5 days',
                'Every result of the primary metric "Checkout" since November 14, 2026 shows the variant "test" as '
                "significant. The results count 2,000 users, and the running time estimate needs about 3,201 to "
                "detect a 30% difference. If this answers your question, end the experiment. When you end it, you "
                "choose whether to roll out a variant.",
                {
                    "variant": "test",
                    "significant_since": "2026-11-14T20:00:00+00:00",
                    "days_significant": 5,
                    "samples": 2000,
                    "planned_samples": 3201,
                    "minimum_detectable_effect": 30,
                },
            ),
            (
                "target_reached_not_significant",
                NOT_SIGNIFICANT_AT_THE_PLAN,
                "The planned sample is reached and no variant is significant",
                'The current result of the primary metric "Checkout" shows no variant as significant. The results '
                "count 2,000 users, and the running time estimate needs about 2,000 to detect a 30% difference. If "
                "this answers your question, end the experiment. When you end it, you choose whether to roll out a "
                "variant. To detect a difference smaller than 30%, keep it running. The running time settings show "
                "what it can detect at each date.",
                {"samples": 2000, "planned_samples": 2000, "minimum_detectable_effect": 30},
            ),
        ]
    )
    def test_states_what_the_results_show(
        self, _name: str, ctx: HealthContext, title: str, detail: str, evidence: dict[str, Any]
    ) -> None:
        finding = result_ready(ctx)

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(
            (finding.code, finding.title, finding.detail, dict(finding.evidence), finding.actions),
            (
                ExperimentHealthFindingCode.RESULT_READY,
                title,
                detail,
                evidence,
                (ExperimentHealthFindingActionKind.END_EXPERIMENT,),
            ),
        )

    def test_reads_the_earliest_significant_variant(self) -> None:
        ctx = _context([("a", 0.5, True), ("b", 0.05, False), ("c", -0.5, True)], significant_days={"a": 1, "c": 2})

        self.assertEqual(
            dict(result_ready_values(ctx)),
            {
                ExperimentHealthValueKey.METRIC_NAME: "Checkout",
                ExperimentHealthValueKey.SAMPLE_COUNT: 4000,
                ExperimentHealthValueKey.PLANNED_SAMPLE_COUNT: 3201,
                ExperimentHealthValueKey.SIGNIFICANT_SINCE_AT: "2026-11-18T08:00:00+00:00",
            },
        )


MEAN = {"kind": "ExperimentMetric", "metric_type": "mean", "source": {"kind": "EventsNode", "event": "purchase"}}


class TestResultReadyFromStoredResults(BaseTest):
    @parameterized.expand(
        [
            ("stayed_significant", {}, True, STAYED_SIGNIFICANT),
            (
                "target_reached_not_significant",
                {"exposure_estimate_config": {"conversionRateInputType": "manual"}, "recommended_sample_size": 1500},
                False,
                TARGET_REACHED_NOT_SIGNIFICANT,
            ),
        ]
    )
    def test_reads_the_stored_results_of_a_mean_metric(
        self, _name: str, running_time_calculation: dict[str, Any], significant: bool, expected_subcode: str
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
        now = timezone.now()
        start = now - timedelta(days=10)
        experiment = Experiment.objects.create(
            team=self.team,
            name="checkout",
            feature_flag=flag,
            start_date=start,
            metrics=[{**MEAN, "uuid": "revenue"}],
            running_time_calculation=running_time_calculation,
        )
        calculation_config = build_primary_calculation_configs(experiment)[0]
        key = calculation_config.calculation_key()
        # A daily point, then a recalculation, then a daily point again: both kinds of rows make up the history.
        for days_ago, fingerprint, display_key in [
            (5, key, calculation_config.legacy_key()),
            (3, _recalc_fingerprint(key), _recalc_fingerprint(calculation_config.legacy_key())),
            (0.1, key, calculation_config.legacy_key()),
        ]:
            ExperimentMetricResult.objects.create(
                experiment=experiment,
                metric_uuid="revenue",
                fingerprint=fingerprint,
                display_key=display_key,
                query_from=start,
                query_to=now - timedelta(days=days_ago),
                completed_at=now - timedelta(days=days_ago),
                status=ExperimentMetricResult.Status.COMPLETED,
                result={
                    "baseline": {"key": "control", "number_of_samples": 1000, "sum": 5000, "sum_squares": 50000},
                    "variant_results": [
                        {
                            "key": "test",
                            "method": "bayesian",
                            "number_of_samples": 1000,
                            "sum": 6000,
                            "sum_squares": 60000,
                            "credible_interval": [0.05, 0.35] if significant else [-0.1, 0.3],
                            "chance_to_win": 0.99 if significant else 0.8,
                            "significant": significant,
                        }
                    ],
                },
            )

        health = get_experiment_health(
            team_id=self.team.id, experiment_id=experiment.id, reader_access=NO_QUERIES, user=self.user
        )

        finding = next(finding for finding in health.findings if finding.check == ExperimentHealthCheckKey.RESULT_READY)
        self.assertEqual(
            (finding.subcode, finding.evidence.get("days_significant")),
            (expected_subcode, 4 if significant else None),
        )
