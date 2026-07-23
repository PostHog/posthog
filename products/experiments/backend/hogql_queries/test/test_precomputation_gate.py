from datetime import UTC, datetime, timedelta

from freezegun import freeze_time

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import EventsNode, ExperimentMeanMetric, ExperimentQuery, PrecomputationMode

from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.hogql_queries.experiment_query_runner import (
    MIN_PRECOMPUTATION_DURATION_SECONDS,
    ExperimentQueryRunner,
    experiment_has_min_runtime_for_precomputation,
    has_uncalculated_cohorts,
)
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest


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

        with freeze_time(now):
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

    @freeze_time("2026-04-30T12:00:00Z")
    def test_team_default_skips_when_under_threshold(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2026, 4, 30, 6, 0, 0),  # 6h before frozen now
        )
        self._enable_precomputation()
        runner = self._build_runner(experiment)
        assert runner._should_precompute() is False

    @freeze_time("2026-04-30T12:00:00Z")
    def test_team_default_enables_when_over_threshold(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2026, 4, 29, 0, 0, 0),  # 36h before frozen now
        )
        self._enable_precomputation()
        runner = self._build_runner(experiment)
        assert runner._should_precompute() is True

    @freeze_time("2026-04-30T12:00:00Z")
    def test_explicit_precomputed_mode_bypasses_gate(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2026, 4, 30, 11, 0, 0),  # 1h before frozen now — under threshold
        )
        self._enable_precomputation()
        runner = self._build_runner(experiment, precomputation_mode=PrecomputationMode.PRECOMPUTED)
        assert runner._should_precompute() is True

    @freeze_time("2026-04-30T12:00:00Z")
    def test_explicit_direct_mode_overrides_passing_gate(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2026, 4, 28, 0, 0, 0),  # well over threshold
        )
        self._enable_precomputation()
        runner = self._build_runner(experiment, precomputation_mode=PrecomputationMode.DIRECT)
        assert runner._should_precompute() is False

    @freeze_time("2026-04-30T12:00:00Z")
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

    @freeze_time("2026-04-30T12:00:00Z")
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
