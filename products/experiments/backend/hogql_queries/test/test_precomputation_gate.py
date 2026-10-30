from datetime import UTC, datetime, timedelta

import time_machine
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    EventsNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentQuery,
    PrecomputationMode,
    StepOrderValue,
)

from posthog.models.team.extensions import get_or_create_team_extension

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.facade.enums import PrecomputeSkipReason
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.metric_events_precompute import MetricEventsPrecompute
from products.experiments.backend.hogql_queries.precompute_policy import (
    MIN_PRECOMPUTATION_DURATION_SECONDS,
    MetricEventsPrecomputePlan,
    experiment_has_min_runtime_for_precomputation,
    has_uncalculated_cohorts,
    metric_events_precompute_plan,
)
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig


class TestPrecomputationDurationGate:
    @parameterized.expand(
        [
            # name, start_offset_seconds, end_offset_seconds (None = no end_date), expected
            ("no_start_date", None, None, False),
            ("draft_no_start", None, 7 * 24 * 3600, False),
            ("just_started_no_end", -60, None, False),
            ("six_hours_old_running", -6 * 3600, 7 * 24 * 3600, False),
            ("just_under_threshold_running", -(MIN_PRECOMPUTATION_DURATION_SECONDS - 60), None, False),
            ("at_threshold_running", -MIN_PRECOMPUTATION_DURATION_SECONDS, None, True),
            ("one_day_old_running", -24 * 3600, 7 * 24 * 3600, True),
            ("future_end_date_short_runtime", -3600, 30 * 24 * 3600, False),
            ("completed_short_in_past", -(8 * 24 * 3600), -(7 * 24 * 3600 + 23 * 3600), False),
            ("completed_long_in_past", -(8 * 24 * 3600), -(7 * 24 * 3600), True),
        ]
    )
    def test_gate(self, _name, start_offset_seconds, end_offset_seconds, expected):
        now = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)
        start_date = None if start_offset_seconds is None else now + timedelta(seconds=start_offset_seconds)
        end_date = None if end_offset_seconds is None else now + timedelta(seconds=end_offset_seconds)

        with time_machine.travel(now, tick=False):
            assert experiment_has_min_runtime_for_precomputation(start_date, end_date) is expected


@override_settings(IN_UNIT_TESTING=True)
class TestShouldPrecomputeRespectsGate(ExperimentQueryRunnerBaseTest):
    def _build_runner(self, experiment, precomputation_mode: PrecomputationMode | None = None) -> ExperimentQueryRunner:
        metric = ExperimentMeanMetric(source=EventsNode(event="purchase"))
        kwargs = {"experiment_id": experiment.id, "kind": "ExperimentQuery", "metric": metric}
        if precomputation_mode is not None:
            kwargs["precomputation_mode"] = precomputation_mode
        query = ExperimentQuery(**kwargs)
        return ExperimentQueryRunner(query=query, team=self.team)

    @time_machine.travel("2026-04-30T12:00:00Z", tick=False)
    def test_team_default_skips_when_under_threshold(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2026, 4, 30, 6, 0, 0),  # 6h before frozen now
        )
        self._enable_precomputation()
        runner = self._build_runner(experiment)
        assert runner._should_precompute() is False

    @time_machine.travel("2026-04-30T12:00:00Z", tick=False)
    def test_team_default_enables_when_over_threshold(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2026, 4, 29, 0, 0, 0),  # 36h before frozen now
        )
        self._enable_precomputation()
        runner = self._build_runner(experiment)
        assert runner._should_precompute() is True

    @time_machine.travel("2026-04-30T12:00:00Z", tick=False)
    def test_explicit_precomputed_mode_bypasses_gate(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2026, 4, 30, 11, 0, 0),  # 1h before frozen now — under threshold
        )
        self._enable_precomputation()
        runner = self._build_runner(experiment, precomputation_mode=PrecomputationMode.PRECOMPUTED)
        assert runner._should_precompute() is True

    @time_machine.travel("2026-04-30T12:00:00Z", tick=False)
    def test_explicit_direct_mode_overrides_passing_gate(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2026, 4, 28, 0, 0, 0),  # well over threshold
        )
        self._enable_precomputation()
        runner = self._build_runner(experiment, precomputation_mode=PrecomputationMode.DIRECT)
        assert runner._should_precompute() is False

    @time_machine.travel("2026-04-30T12:00:00Z", tick=False)
    def test_team_disabled_skips_regardless_of_gate(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2026, 4, 28, 0, 0, 0),  # well over threshold
        )
        self._disable_precomputation()
        runner = self._build_runner(experiment)
        assert runner._should_precompute() is False


def _cohort_exposure_criteria(cohort_id: int) -> dict:
    return {
        "exposure_config": {
            "kind": "ExperimentEventExposureConfig",
            "event": "$feature_flag_called",
            "properties": [{"key": "id", "type": "cohort", "value": cohort_id, "operator": "in"}],
        }
    }


@override_settings(IN_UNIT_TESTING=True)
class TestUncalculatedCohortGate(ExperimentQueryRunnerBaseTest):
    @parameterized.expand(
        [
            # name, is_static, version, is_calculating, expected
            ("dynamic_never_calculated", False, None, True, True),
            ("dynamic_calculated", False, 1, False, False),
            ("dynamic_mid_recalculation", False, 3, True, False),
            ("static_populating", True, None, True, True),
            ("static_populated", True, None, False, False),
        ]
    )
    def test_cohort_states(self, _name, is_static, version, is_calculating, expected):
        cohort = Cohort.objects.create(team=self.team, name="test cohort", is_static=is_static)
        Cohort.objects.filter(pk=cohort.pk).update(version=version, is_calculating=is_calculating)

        assert has_uncalculated_cohorts(self.team, _cohort_exposure_criteria(cohort.pk)) is expected

    def test_no_cohort_references_returns_false(self):
        criteria = {
            "exposure_config": {
                "kind": "ExperimentEventExposureConfig",
                "event": "$feature_flag_called",
                "properties": [{"key": "email", "type": "person", "value": "@x.com", "operator": "icontains"}],
            }
        }
        assert has_uncalculated_cohorts(self.team, criteria, None) is False

    def test_finds_cohort_in_pydantic_metric(self):
        cohort = Cohort.objects.create(team=self.team, name="test cohort")
        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", properties=[{"key": "id", "type": "cohort", "value": cohort.pk}])
        )
        assert has_uncalculated_cohorts(self.team, metric) is True

    @time_machine.travel("2026-04-30T12:00:00Z", tick=False)
    def test_should_precompute_waits_for_first_cohort_calculation(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2026, 4, 29, 0, 0, 0),  # over the duration threshold
        )
        cohort = Cohort.objects.create(team=self.team, name="fresh cohort", is_calculating=True)
        experiment.exposure_criteria = _cohort_exposure_criteria(cohort.pk)
        experiment.save()
        self._enable_precomputation()

        metric = ExperimentMeanMetric(source=EventsNode(event="purchase"))
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)
        assert runner._should_precompute() is False
        assert runner._precompute_skip_reason() == "cohort_not_calculated"

        Cohort.objects.filter(pk=cohort.pk).update(version=1, is_calculating=False)
        assert runner._should_precompute() is True
        assert runner._precompute_skip_reason() is None


@override_settings(IN_UNIT_TESTING=True)
class TestMetricEventsPrecomputePlan(ExperimentQueryRunnerBaseTest):
    @parameterized.expand(
        [
            # name, metric-events overrides, experiment age, exposure criteria, metric reason, team reason
            ("eligible", {}, timedelta(days=3), None, None, None),
            ("group_aggregation", {"group_type_index": 0}, timedelta(days=3), None, "group_aggregation", None),
            ("breakdown", {"has_breakdowns": True}, timedelta(days=3), None, "breakdown", None),
            ("cuped", {"cuped_enabled": True}, timedelta(days=3), None, "cuped", None),
            ("data_warehouse", {"is_data_warehouse_query": True}, timedelta(days=3), None, "data_warehouse", None),
            (
                "unordered_funnel",
                {
                    "metric": ExperimentFunnelMetric(
                        series=[EventsNode(event="signup"), EventsNode(event="purchase")],
                        funnel_order_type=StepOrderValue.UNORDERED,
                    )
                },
                timedelta(days=3),
                None,
                "funnel_order_type",
                None,
            ),
            ("team_disabled", {}, timedelta(days=3), None, None, PrecomputeSkipReason.TEAM_DISABLED),
            ("young_experiment", {}, timedelta(hours=1), None, None, PrecomputeSkipReason.MIN_RUNTIME),
            ("activation_exposures", {}, timedelta(days=3), "activation", None, PrecomputeSkipReason.ACTIVATION_CONFIG),
            (
                "uncalculated_cohort",
                {},
                timedelta(days=3),
                "cohort",
                None,
                PrecomputeSkipReason.COHORT_NOT_CALCULATED,
            ),
            ("metric_rule_before_team_gate", {"has_breakdowns": True}, timedelta(hours=1), None, "breakdown", None),
        ]
    )
    @time_machine.travel("2026-04-30T12:00:00Z", tick=False)
    def test_plan(self, name, overrides, age, exposure, metric_reason, team_reason):
        experiment = self.create_experiment(
            feature_flag=self.create_feature_flag(key=f"plan-{name}"),
            start_date=datetime(2026, 4, 30, 12, 0, 0) - age,
        )
        if exposure == "activation":
            experiment.exposure_criteria = {"activation_config": {"event": "signed up", "properties": []}}
        elif exposure == "cohort":
            cohort = Cohort.objects.create(team=self.team, name="fresh cohort", is_calculating=True)
            experiment.exposure_criteria = _cohort_exposure_criteria(cohort.pk)
        experiment.save()
        if team_reason == PrecomputeSkipReason.TEAM_DISABLED:
            self._disable_precomputation()
        else:
            self._enable_precomputation()
        metric_events = MetricEventsPrecompute(
            **{
                "team": self.team,
                "experiment": experiment,
                "as_of": datetime.now(UTC),
                "metric": ExperimentMeanMetric(source=EventsNode(event="purchase")),
                "group_type_index": None,
                "has_breakdowns": False,
                "cuped_enabled": False,
                "is_data_warehouse_query": False,
                **overrides,
            }
        )

        plan = metric_events_precompute_plan(
            get_or_create_team_extension(self.team, TeamExperimentsConfig), metric_events
        )

        assert plan == MetricEventsPrecomputePlan(metric_skip_reason=metric_reason, team_skip_reason=team_reason)
        assert plan.reads_precomputed is (metric_reason is None and team_reason is None)

    @parameterized.expand(
        [
            ("plan_reads_precomputed", MetricEventsPrecomputePlan(), True),
            ("plan_blocks", MetricEventsPrecomputePlan(metric_skip_reason="cuped"), False),
        ]
    )
    @time_machine.travel("2026-04-30T12:00:00Z", tick=False)
    def test_runner_builds_metric_events_only_when_the_plan_allows(self, _name, plan, expect_build):
        experiment = self.create_experiment(
            feature_flag=self.create_feature_flag(), start_date=datetime(2026, 4, 27, 0, 0, 0)
        )
        self._enable_precomputation()
        query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=ExperimentMeanMetric(source=EventsNode(event="purchase")),
        )
        runner = ExperimentQueryRunner(query=query, team=self.team)
        not_ready = LazyComputationResult(ready=False, job_ids=[])

        with (
            patch(
                "products.experiments.backend.hogql_queries.experiment_query_runner.metric_events_precompute_plan",
                return_value=plan,
            ),
            patch(
                "products.experiments.backend.hogql_queries.precompute_policy.ensure_precomputed",
                return_value=not_ready,
            ) as exposures_build,
            patch(
                "products.experiments.backend.hogql_queries.metric_events_precompute.ensure_precomputed",
                return_value=not_ready,
            ) as metric_events_build,
        ):
            runner._get_experiment_query()

        assert exposures_build.called
        assert metric_events_build.called is expect_build
